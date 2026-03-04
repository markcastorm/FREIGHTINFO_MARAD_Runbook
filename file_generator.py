"""
FREIGHTINFO_MARAD Runbook - File Generator
Generates XLS DATA, XLS META, and ZIP output files from master data.
"""

import os
import shutil
import logging
import zipfile

import xlwt

import config

logger = logging.getLogger(__name__)


class FREIGHTINFOFileGenerator:

    def __init__(self):
        pass

    def create_xls_file(self, header_lines, data_rows, output_dir):
        """
        Generate XLS DATA file from master data.
        Mirrors the master CSV structure: 2-row header + data rows.
        """
        os.makedirs(output_dir, exist_ok=True)
        filepath = os.path.join(output_dir, config.DATA_FILE_PATTERN)

        try:
            wb = xlwt.Workbook()
            ws = wb.add_sheet('DATA')

            # Write header row 1: column codes
            header1_parts = header_lines[0].split(',')
            for col_idx, val in enumerate(header1_parts):
                ws.write(0, col_idx, val.strip())

            # Write header row 2: column descriptions
            header2_parts = header_lines[1].split(',')
            for col_idx, val in enumerate(header2_parts):
                ws.write(1, col_idx, val.strip())

            # Write data rows
            for row_idx, row in enumerate(data_rows, start=2):
                # Column 0: week code (string)
                if row:
                    ws.write(row_idx, 0, row[0])

                # Columns 1+: values (as integers where possible)
                for col_idx in range(1, min(len(row), len(config.OUTPUT_COLUMN_CODES) + 1)):
                    val = row[col_idx].strip() if col_idx < len(row) else ''
                    if val:
                        try:
                            ws.write(row_idx, col_idx, int(val))
                        except (ValueError, TypeError):
                            ws.write(row_idx, col_idx, val)
                    else:
                        ws.write(row_idx, col_idx, '')

            wb.save(filepath)
            logger.info(f"DATA XLS created: {filepath}")
            return filepath

        except Exception as e:
            logger.error(f"Error creating DATA XLS: {e}")
            return None

    def create_meta_file(self, output_dir):
        """Generate XLS META file with static metadata from config."""
        os.makedirs(output_dir, exist_ok=True)
        filepath = os.path.join(output_dir, config.META_FILE_PATTERN)

        try:
            wb = xlwt.Workbook()
            ws = wb.add_sheet('META')

            # Write header row
            for col_idx, col_name in enumerate(config.META_COLUMNS):
                ws.write(0, col_idx, col_name)

            # Write metadata rows (one per timeseries)
            for row_idx, meta_row in enumerate(config.META_ROWS, start=1):
                for col_idx, col_name in enumerate(config.META_COLUMNS):
                    ws.write(row_idx, col_idx, meta_row.get(col_name, ''))

            wb.save(filepath)
            logger.info(f"META XLS created: {filepath}")
            return filepath

        except Exception as e:
            logger.error(f"Error creating META XLS: {e}")
            return None

    def create_zip_file(self, data_file, meta_file, output_dir):
        """Create ZIP containing DATA and META XLS files."""
        os.makedirs(output_dir, exist_ok=True)
        filepath = os.path.join(output_dir, config.ZIP_FILE_PATTERN)

        try:
            with zipfile.ZipFile(filepath, 'w', zipfile.ZIP_DEFLATED) as zf:
                if data_file and os.path.exists(data_file):
                    zf.write(data_file, os.path.basename(data_file))
                if meta_file and os.path.exists(meta_file):
                    zf.write(meta_file, os.path.basename(meta_file))

            logger.info(f"ZIP created: {filepath}")
            return filepath

        except Exception as e:
            logger.error(f"Error creating ZIP: {e}")
            return None

    def copy_to_latest(self, files, latest_dir):
        """Copy generated files to the 'latest' directory."""
        os.makedirs(latest_dir, exist_ok=True)

        # Remove existing files in latest
        for existing in os.listdir(latest_dir):
            existing_path = os.path.join(latest_dir, existing)
            if os.path.isfile(existing_path):
                os.remove(existing_path)

        for file_type, filepath in files.items():
            if filepath and os.path.exists(filepath):
                dest = os.path.join(latest_dir, os.path.basename(filepath))
                shutil.copy2(filepath, dest)
                logger.info(f"  Copied to latest: {os.path.basename(filepath)}")

    def generate_files(self, header_lines, data_rows):
        """
        Main method: generate all output files.
        Returns dict with file paths.
        """
        logger.info("=" * 70)
        logger.info("Generating output files...")
        logger.info(f"Output directory: {config.OUTPUT_DIR}")
        logger.info("=" * 70)

        output_files = {}

        # Create DATA XLS
        data_file = self.create_xls_file(header_lines, data_rows, config.OUTPUT_DIR)
        output_files['data'] = data_file

        # Create META XLS
        meta_file = self.create_meta_file(config.OUTPUT_DIR)
        output_files['meta'] = meta_file

        # Create ZIP
        if data_file and meta_file:
            zip_file = self.create_zip_file(data_file, meta_file, config.OUTPUT_DIR)
            output_files['zip'] = zip_file

        # Copy to latest
        self.copy_to_latest(output_files, config.LATEST_OUTPUT_DIR)

        logger.info("File generation complete")
        return output_files
