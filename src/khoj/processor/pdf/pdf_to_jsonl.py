# Standard Packages
import os
import logging
from typing import List
import base64

# External Packages
from langchain.document_loaders import PyMuPDFLoader

# Internal Packages
from khoj.processor.text_to_jsonl import TextEmbeddings
from khoj.utils.helpers import timer
from khoj.utils.jsonl import compress_jsonl_data
from khoj.utils.rawconfig import Entry
from database.models import Embeddings, KhojUser


logger = logging.getLogger(__name__)


class PdfToJsonl(TextEmbeddings):
    # Define Functions
    def process(self, files: dict[str, str] = None, full_corpus: bool = True, user: KhojUser = None):
        # Extract required fields from config
        if not full_corpus:
            deletion_file_names = set([file for file in files if files[file] == ""])
            files_to_process = set(files) - deletion_file_names
            files = {file: files[file] for file in files_to_process}
        else:
            deletion_file_names = None

        # Extract Entries from specified Pdf files
        with timer("Parse entries from PDF files into dictionaries", logger):
            current_entries = PdfToJsonl.convert_pdf_entries_to_maps(*PdfToJsonl.extract_pdf_entries(files))

        # Split entries by max tokens supported by model
        with timer("Split entries by max token size supported by model", logger):
            current_entries = self.split_entries_by_max_tokens(current_entries, max_tokens=256)

        # Identify, mark and merge any new entries with previous entries
        with timer("Identify new or updated entries", logger):
            entries_with_ids = self.update_embeddings(
                current_entries, Embeddings.EmbeddingsType.MARKDOWN, "compiled", logger, deletion_file_names, user
            )

        return entries_with_ids

    @staticmethod
    def extract_pdf_entries(pdf_files):
        """Extract entries by page from specified PDF files"""

        entries = []
        entry_to_location_map = []
        for pdf_file in pdf_files:
            try:
                # Write the PDF file to a temporary file, as it is stored in byte format in the pdf_file object and the PyPDFLoader expects a file path
                tmp_file = f"tmp_pdf_file.pdf"
                with open(f"{tmp_file}", "wb") as f:
                    bytes = base64.b64decode(pdf_files[pdf_file])
                    f.write(bytes)
                loader = PyMuPDFLoader(f"{tmp_file}")
                pdf_entries_per_file = [page.page_content for page in loader.load()]
                entry_to_location_map += zip(pdf_entries_per_file, [pdf_file] * len(pdf_entries_per_file))
                entries.extend(pdf_entries_per_file)
            except Exception as e:
                logger.warning(f"Unable to process file: {pdf_file}. This file will not be indexed.")
                logger.warning(e)
            finally:
                if os.path.exists(f"{tmp_file}"):
                    os.remove(f"{tmp_file}")

        return entries, dict(entry_to_location_map)

    @staticmethod
    def convert_pdf_entries_to_maps(parsed_entries: List[str], entry_to_file_map) -> List[Entry]:
        "Convert each PDF entries into a dictionary"
        entries = []
        for parsed_entry in parsed_entries:
            entry_filename = entry_to_file_map[parsed_entry]
            # Append base filename to compiled entry for context to model
            heading = f"{entry_filename}\n"
            compiled_entry = f"{heading}{parsed_entry}"
            entries.append(
                Entry(
                    compiled=compiled_entry,
                    raw=parsed_entry,
                    heading=heading,
                    file=f"{entry_filename}",
                )
            )

        logger.debug(f"Converted {len(parsed_entries)} PDF entries to dictionaries")

        return entries

    @staticmethod
    def convert_pdf_maps_to_jsonl(entries: List[Entry]):
        "Convert each PDF entry to JSON and collate as JSONL"
        return "".join([f"{entry.to_json()}\n" for entry in entries])
