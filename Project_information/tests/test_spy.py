"""
test_spy.py  —  Passive diagnostics observer for the BTS Tableau chart.

HOW TO USE:
  1. Run this script.  A Chrome window opens and navigates to the chart.
  2. The script waits 15 s for the page to settle, then injects the spy code.
  3. You interact manually:
       - Hover over the canvas
       - Hover over the legend
       - Click the "Highlight Selected Items" button
       - Click East / West / Gulf legend items
       - Hover back over the canvas
  4. Every 2 seconds the script polls and logs what changed.
  5. Press Ctrl+C to finish — a full event dump is written to the log file.

What is captured (inside the Tableau iframe):
  DOM_ATTR   — any element attribute change (class, style, aria-*, opacity, etc.)
  DOM_CHILD  — nodes added or removed anywhere in the DOM
  DOM_TEXT   — text node content changes (tooltip text updates)
  XHR_SEND   — outgoing XMLHttpRequest calls (URL + body)
  XHR_RESP   — XHR response received (URL + status + length)
  FETCH      — outgoing fetch() calls
  FETCH_RESP — fetch response received
  MOUSE      — mouse moving onto a new element (class / tag transition logged)
  CLICK      — any click, what element, its text, coordinates
  TOOLTIP    — tooltip text content any time it changes
  LEGEND_BTN — highlight button aria-pressed state change
  LEGEND_SEL — legend item aria-selected change
  CONSOLE    — console.log / console.warn / console.error from inside the frame

Log files land in:  logs/spy_<timestamp>/spy_<timestamp>.log
"""

import os
import re
import sys
import time
import json
import logging
from datetime import datetime

import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains

# ─── Logging ──────────────────────────────────────────────────────────────────
_RUN_TS  = datetime.now().strftime('%Y%m%d_%H%M%S')
_LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs', f'spy_{_RUN_TS}')
os.makedirs(_LOG_DIR, exist_ok=True)
_LOG_FILE = os.path.join(_LOG_DIR, f'spy_{_RUN_TS}.log')

_fmt  = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s')
_root = logging.getLogger()
_root.setLevel(logging.DEBUG)
_root.handlers.clear()

_fh = logging.FileHandler(_LOG_FILE, encoding='utf-8')
_fh.setFormatter(_fmt)
_root.addHandler(_fh)

_ch = logging.StreamHandler()
_ch.setFormatter(_fmt)
_root.addHandler(_ch)

log = logging.getLogger(__name__)
log.info(f"=== SPY SESSION STARTED ===")
log.info(f"Log file: {_LOG_FILE}")

# ─── Constants ────────────────────────────────────────────────────────────────
BASE_URL   = "https://www.bts.gov/freight-indicators#anchored-offshore"
IFRAME_KEY = 'ContainershipsAnchored'

# ─── JS spy injected into the iframe ──────────────────────────────────────────
SPY_JS = r"""
(function() {
    // Avoid double-injection
    if (window.__spyActive) return 'ALREADY_ACTIVE';
    window.__spyActive = true;

    window.__spy = { events: [], _seen: {} };

    function record(type, data) {
        window.__spy.events.push({
            ts:   new Date().toISOString(),
            type: type,
            data: data
        });
    }

    // ── 1. DOM MutationObserver ───────────────────────────────────────────────
    var _mo = new MutationObserver(function(mutations) {
        mutations.forEach(function(m) {

            // Attribute changed
            if (m.type === 'attributes') {
                var el  = m.target;
                var tag = el.tagName + (el.id ? '#' + el.id : '') +
                          (el.className && typeof el.className === 'string'
                              ? '.' + el.className.trim().replace(/\s+/g,'.')
                              : '');
                record('DOM_ATTR', {
                    el:    tag.substring(0, 120),
                    attr:  m.attributeName,
                    old:   m.oldValue,
                    new:   el.getAttribute(m.attributeName)
                });
            }

            // Child nodes added / removed
            else if (m.type === 'childList') {
                var added = [], removed = [];
                m.addedNodes.forEach(function(n) {
                    var desc = n.nodeName;
                    if (n.className && typeof n.className === 'string')
                        desc += '.' + n.className.trim().replace(/\s+/g,'.').substring(0,60);
                    added.push(desc);
                });
                m.removedNodes.forEach(function(n) {
                    var desc = n.nodeName;
                    if (n.className && typeof n.className === 'string')
                        desc += '.' + n.className.trim().replace(/\s+/g,'.').substring(0,60);
                    removed.push(desc);
                });
                if (added.length || removed.length) {
                    var par = m.target.tagName +
                              (typeof m.target.className === 'string'
                                  ? '.' + m.target.className.trim().replace(/\s+/g,'.').substring(0,60)
                                  : '');
                    record('DOM_CHILD', { parent: par, added: added, removed: removed });
                }
            }

            // Text content changed
            else if (m.type === 'characterData') {
                var txt = (m.target.textContent || '').trim();
                if (txt) {
                    var par2 = m.target.parentElement
                        ? m.target.parentElement.tagName + '.' +
                          (m.target.parentElement.className || '').substring(0,60)
                        : '?';
                    record('DOM_TEXT', {
                        parent: par2,
                        old:    (m.oldValue || '').trim().substring(0, 120),
                        new:    txt.substring(0, 120)
                    });
                }
            }
        });
    });
    _mo.observe(document.body || document.documentElement, {
        childList:              true,
        subtree:                true,
        attributes:             true,
        attributeOldValue:      true,
        characterData:          true,
        characterDataOldValue:  true
    });

    // ── 2. XHR interception ────────────────────────────────────────────────────
    var _origOpen = XMLHttpRequest.prototype.open;
    var _origSend = XMLHttpRequest.prototype.send;

    XMLHttpRequest.prototype.open = function(method, url) {
        this.__spyMethod = method;
        this.__spyUrl    = url;
        return _origOpen.apply(this, arguments);
    };
    XMLHttpRequest.prototype.send = function(body) {
        var self = this;
        record('XHR_SEND', {
            method: self.__spyMethod,
            url:    (self.__spyUrl || '').substring(0, 300),
            body:   body ? body.toString().substring(0, 300) : null
        });
        self.addEventListener('load', function() {
            record('XHR_RESP', {
                url:    (self.__spyUrl || '').substring(0, 200),
                status: self.status,
                bytes:  self.responseText ? self.responseText.length : 0,
                preview: self.responseText ? self.responseText.substring(0, 200) : null
            });
        });
        self.addEventListener('error', function() {
            record('XHR_ERR', { url: (self.__spyUrl || '').substring(0, 200) });
        });
        return _origSend.apply(this, arguments);
    };

    // ── 3. fetch() interception ────────────────────────────────────────────────
    if (window.fetch) {
        var _origFetch = window.fetch.bind(window);
        window.fetch = function(resource, init) {
            var url = (typeof resource === 'string') ? resource : resource.url;
            record('FETCH', {
                method: (init && init.method) ? init.method : 'GET',
                url:    url.substring(0, 300),
                body:   (init && init.body) ? init.body.toString().substring(0, 200) : null
            });
            return _origFetch(resource, init).then(function(resp) {
                record('FETCH_RESP', { url: url.substring(0, 200), status: resp.status });
                return resp;
            }, function(err) {
                record('FETCH_ERR', { url: url.substring(0, 200), err: err.toString() });
                throw err;
            });
        };
    }

    // ── 4. Mouse events (throttled to element-boundary transitions) ────────────
    var _lastEl = '';
    document.addEventListener('mousemove', function(e) {
        var el  = e.target;
        var cls = typeof el.className === 'string' ? el.className.trim().substring(0,80) : '';
        var sig = el.tagName + (el.id ? '#' + el.id : '') + (cls ? ' [' + cls + ']' : '');
        if (sig !== _lastEl) {
            _lastEl = sig;
            record('MOUSE_ENTER', { el: sig, x: Math.round(e.clientX), y: Math.round(e.clientY) });
        }
    }, true);

    document.addEventListener('mousedown', function(e) {
        var el = e.target;
        record('MOUSEDOWN', {
            el:   (el.tagName + ' ' + (typeof el.className === 'string' ? el.className : '')).substring(0,100),
            id:   el.id || null,
            x:    Math.round(e.clientX),
            y:    Math.round(e.clientY)
        });
    }, true);

    document.addEventListener('click', function(e) {
        var el = e.target;
        record('CLICK', {
            el:   (el.tagName + ' ' + (typeof el.className === 'string' ? el.className : '')).substring(0,100),
            id:   el.id || null,
            text: el.innerText ? el.innerText.substring(0, 80) : null,
            x:    Math.round(e.clientX),
            y:    Math.round(e.clientY)
        });
    }, true);

    // ── 5. Tooltip watcher (50ms poll) ────────────────────────────────────────
    var _lastTip = '';
    setInterval(function() {
        var sels = [
            '.tab-tooltip',
            '.tab-beautified-tooltip',
            '.tab-glass-content',
            '[data-tb-test-id="tooltip-container"]'
        ];
        for (var i = 0; i < sels.length; i++) {
            var el = document.querySelector(sels[i]);
            if (el) {
                var txt = el.innerText ? el.innerText.trim() : '';
                var vis = el.style.display !== 'none' &&
                          el.style.visibility !== 'hidden' &&
                          el.style.opacity !== '0';
                var key = (vis ? 'SHOW' : 'HIDE') + '|' + txt;
                if (key !== _lastTip) {
                    _lastTip = key;
                    record('TOOLTIP', {
                        selector: sels[i],
                        visible:  vis,
                        display:  el.style.display,
                        opacity:  el.style.opacity,
                        text:     txt.substring(0, 300)
                    });
                }
                break;
            }
        }
    }, 50);

    // ── 6. Legend state watcher (100ms poll) ──────────────────────────────────
    var _lastBtn     = null;
    var _lastLegend  = {};
    var _lastCtrlOp  = null;

    setInterval(function() {
        // Highlight button
        var btn = document.querySelector('.tabLegendHighlighterButton');
        if (btn) {
            var state = btn.getAttribute('aria-pressed');
            if (state !== _lastBtn) {
                _lastBtn = state;
                record('LEGEND_BTN', {
                    aria_pressed: state,
                    class:        btn.className,
                    display:      btn.style.display,
                    opacity:      btn.style.opacity || getComputedStyle(btn).opacity
                });
            }
        }

        // Controls container opacity
        var ctrl = document.querySelector('.tabLegendTitleControls');
        if (ctrl) {
            var op = ctrl.style.opacity || getComputedStyle(ctrl).opacity;
            if (op !== _lastCtrlOp) {
                _lastCtrlOp = op;
                record('LEGEND_CTRL_OPACITY', { opacity: op, display: ctrl.style.display });
            }
        }

        // Legend items
        var items = document.querySelectorAll('.tabLegendItem');
        items.forEach(function(item) {
            var label = item.querySelector('.tabLegendItemLabel');
            var name  = label ? label.innerText.trim() : item.innerText.trim().substring(0,20);
            var sel   = item.getAttribute('aria-selected');
            var col   = '';
            var swatch = item.querySelector('.tabColorLegendSwatch, [class*="swatch"], [class*="color"]');
            if (swatch) col = swatch.style.backgroundColor || '';
            var key = name + '|' + sel + '|' + col;
            if (_lastLegend[name] !== key) {
                _lastLegend[name] = key;
                record('LEGEND_SEL', { name: name, aria_selected: sel, color: col });
            }
        });
    }, 100);

    // ── 7. Console override ────────────────────────────────────────────────────
    ['log','warn','error','info'].forEach(function(lvl) {
        var orig = console[lvl].bind(console);
        console[lvl] = function() {
            var msg = Array.from(arguments).map(function(a) {
                try { return typeof a === 'object' ? JSON.stringify(a) : String(a); }
                catch(e) { return '[unserializable]'; }
            }).join(' ');
            record('CONSOLE_' + lvl.toUpperCase(), { msg: msg.substring(0, 300) });
            return orig.apply(console, arguments);
        };
    });

    return 'SPY ACTIVE — watching DOM/XHR/Fetch/Mouse/Tooltip/Legend/Console';
})();
"""

DRAIN_JS = """
(function() {
    if (!window.__spy) return [];
    var batch = window.__spy.events.splice(0);   // drain the queue atomically
    return batch;
})();
"""

# ─── Event printer ────────────────────────────────────────────────────────────

# Colour (when supported) — just level prefixes for the log
_TYPE_ICONS = {
    'TOOLTIP':           '💬',
    'LEGEND_BTN':        '🔘',
    'LEGEND_SEL':        '⭐',
    'LEGEND_CTRL_OPACITY': '👁️ ',
    'CLICK':             '🖱️ ',
    'MOUSEDOWN':         '🖱️ ',
    'MOUSE_ENTER':       '→ ',
    'DOM_ATTR':          '🔧',
    'DOM_CHILD':         '🌳',
    'DOM_TEXT':          '📝',
    'XHR_SEND':          '📤',
    'XHR_RESP':          '📥',
    'XHR_ERR':           '❌',
    'FETCH':             '📤',
    'FETCH_RESP':        '📥',
    'FETCH_ERR':         '❌',
    'CONSOLE_LOG':       '🖥️ ',
    'CONSOLE_WARN':      '⚠️ ',
    'CONSOLE_ERROR':     '🔴',
    'CONSOLE_INFO':      '🔵',
}

# Events to suppress in the console (too noisy) — still saved to log file
_QUIET_TYPES = {'MOUSE_ENTER'}

_last_drain_count = 0


def log_event(evt):
    t    = evt.get('type', '?')
    ts   = evt.get('ts', '')[-12:]        # keep only time part
    d    = evt.get('data', {})
    icon = _TYPE_ICONS.get(t, '   ')

    if t == 'TOOLTIP':
        line = f"{icon} TOOLTIP  visible={d.get('visible')} opacity={d.get('opacity')!r:>5}  text={d.get('text','')!r}"
    elif t == 'LEGEND_BTN':
        line = f"{icon} LEGEND_BTN  aria-pressed={d.get('aria_pressed')}  class={d.get('class','')}"
    elif t == 'LEGEND_SEL':
        line = f"{icon} LEGEND_SEL  name={d.get('name')}  aria-selected={d.get('aria_selected')}  color={d.get('color')}"
    elif t == 'LEGEND_CTRL_OPACITY':
        line = f"{icon} CTRL_OPACITY  opacity={d.get('opacity')}"
    elif t in ('CLICK', 'MOUSEDOWN'):
        line = f"{icon} {t}  el={d.get('el','')}  text={d.get('text','')!r}  @({d.get('x')},{d.get('y')})"
    elif t == 'MOUSE_ENTER':
        line = f"{icon} MOUSE  {d.get('el','')}  @({d.get('x')},{d.get('y')})"
    elif t == 'DOM_ATTR':
        line = f"{icon} DOM_ATTR  [{d.get('el','')}]  {d.get('attr')}:  {d.get('old')!r} → {d.get('new')!r}"
    elif t == 'DOM_CHILD':
        line = f"{icon} DOM_CHILD  parent={d.get('parent','')}  +{d.get('added',[])}  -{d.get('removed',[])}"
    elif t == 'DOM_TEXT':
        line = f"{icon} DOM_TEXT  [{d.get('parent','')}]  {d.get('old','')!r} → {d.get('new','')!r}"
    elif t in ('XHR_SEND', 'FETCH'):
        line = f"{icon} {t}  {d.get('method','?')} {d.get('url','')}"
    elif t in ('XHR_RESP', 'FETCH_RESP'):
        line = f"{icon} {t}  status={d.get('status')}  bytes={d.get('bytes','-')}  {d.get('url','')}"
    elif t.startswith('CONSOLE'):
        line = f"{icon} {t}  {d.get('msg','')}"
    else:
        line = f"   {t}  {json.dumps(d, ensure_ascii=False)[:200]}"

    full = f"[{ts}] {line}"

    # Always write to file
    log.info(full)

    # Console: skip noisy MOUSE_ENTER unless it's something interesting
    if t not in _QUIET_TYPES:
        print(full)


# ─── Main ─────────────────────────────────────────────────────────────────────

def run():
    options = uc.ChromeOptions()
    options.add_argument('--window-size=1440,900')
    driver = uc.Chrome(options=options, version_main=149)

    try:
        log.info(f"Loading: {BASE_URL}")
        driver.get(BASE_URL)
        time.sleep(6)

        # Scroll to chart section
        try:
            link = driver.find_element(By.CSS_SELECTOR, 'a[href="#anchored-offshore"]')
            driver.execute_script("arguments[0].click();", link)
            time.sleep(3)
        except Exception:
            driver.execute_script("window.location.hash='anchored-offshore';")
            time.sleep(2)

        # ── Find iframe ────────────────────────────────────────────────────────
        log.info("Searching for Tableau iframe ...")
        iframe = None
        for _ in range(25):
            for f in driver.find_elements(By.TAG_NAME, 'iframe'):
                src = f.get_attribute('src') or ''
                if IFRAME_KEY in src:
                    iframe = f
                    log.info(f"  Found iframe: {src[:120]}")
                    break
            if iframe:
                break
            driver.execute_script("window.scrollBy(0, 300);")
            time.sleep(1)

        if not iframe:
            log.error("Iframe not found — chart may not have loaded")
            return

        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", iframe)
        driver.switch_to.frame(iframe)
        log.info("Inside iframe — waiting 10 s for Tableau to fully load ...")
        time.sleep(10)

        # ── Inject spy ─────────────────────────────────────────────────────────
        result = driver.execute_script(SPY_JS)
        log.info(f"Spy injection result: {result}")

        # ── Capture initial legend state ───────────────────────────────────────
        init_state = driver.execute_script("""
        (function() {
            var out = {};
            var btn = document.querySelector('.tabLegendHighlighterButton');
            if (btn) {
                out.highlight_btn = {
                    aria_pressed: btn.getAttribute('aria-pressed'),
                    class: btn.className,
                    computed_opacity: getComputedStyle(btn).opacity,
                    computed_display: getComputedStyle(btn).display,
                    computed_pointer: getComputedStyle(btn).pointerEvents
                };
            } else {
                out.highlight_btn = 'NOT FOUND';
            }
            var ctrl = document.querySelector('.tabLegendTitleControls');
            if (ctrl) {
                out.ctrl_div = {
                    computed_opacity: getComputedStyle(ctrl).opacity,
                    computed_display: getComputedStyle(ctrl).display,
                    computed_pointer: getComputedStyle(ctrl).pointerEvents,
                    inline_style: ctrl.getAttribute('style')
                };
            } else {
                out.ctrl_div = 'NOT FOUND';
            }
            var items = [];
            document.querySelectorAll('.tabLegendItem').forEach(function(el) {
                var label = el.querySelector('.tabLegendItemLabel');
                items.push({
                    name: label ? label.innerText.trim() : '?',
                    aria_selected: el.getAttribute('aria-selected'),
                    computed_opacity: getComputedStyle(el).opacity
                });
            });
            out.legend_items = items;
            var canvases = document.querySelectorAll('canvas');
            out.canvases = Array.from(canvases).map(function(c) {
                return { w: c.width, h: c.height, displayed: c.style.display };
            });
            return out;
        })();
        """)

        log.info("=== INITIAL STATE SNAPSHOT ===")
        log.info(json.dumps(init_state, indent=2))
        print("\n=== INITIAL STATE SNAPSHOT ===")
        print(json.dumps(init_state, indent=2))

        # ── Polling loop ───────────────────────────────────────────────────────
        print("\n" + "="*70)
        print("SPY IS ACTIVE")
        print("Interact with the chart manually — hover, click, scroll.")
        print("All events are logged in real time.")
        print(f"Log file: {_LOG_FILE}")
        print("Press Ctrl+C to stop.")
        print("="*70 + "\n")

        total_events = 0
        try:
            while True:
                time.sleep(2)
                try:
                    batch = driver.execute_script(DRAIN_JS)
                except Exception:
                    # Page might be navigating
                    continue

                if batch:
                    for evt in batch:
                        log_event(evt)
                    total_events += len(batch)
                    print(f"  — [{datetime.now().strftime('%H:%M:%S')}] {len(batch)} events this tick | {total_events} total —")

        except KeyboardInterrupt:
            print("\nCtrl+C received — stopping.")

        # ── Final drain ────────────────────────────────────────────────────────
        try:
            final_batch = driver.execute_script(DRAIN_JS)
            for evt in final_batch:
                log_event(evt)
            total_events += len(final_batch)
        except Exception:
            pass

        log.info(f"=== SESSION ENDED  {total_events} total events logged ===")
        print(f"\nDone.  {total_events} events written to:\n  {_LOG_FILE}")

    finally:
        input("\nPress ENTER to close the browser...")
        try:
            driver.quit()
        except Exception:
            pass


if __name__ == "__main__":
    run()
