# bulk_upload_to_library.py
Bulk upload FASTQ files from server to Galaxy.

This is a little bit of code to make it easier to upload many (> 1000) fastq files to a Galaxy server, renaming the files to the name of the file (presumably the sample name). It uses `parsec` (in the future, `bioblend`), `tqdm`, and Python 3.7 features like `asyncio`.
