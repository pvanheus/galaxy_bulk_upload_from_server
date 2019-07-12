# bulk_upload_to_library.py
Bulk upload FASTQ files from server to Galaxy.

This is a little bit of code to make it easier to upload many (> 1000) fastq files to a Galaxy server, renaming the files to the name of the file (presumably the sample name). It uses the Galaxy API via `bioblend`, `tqdm` (for a bit of pretty progress reporting), and Python 3.7 features like `asyncio`.

Due to a quirk in Galaxy, the renaming of the datasets to their final name can only happen after Galaxy has processed them and declared them 'ok'. To ensure that this does not slow down the uploading, the renaming of files is done by asynchronously after the upload of each dataset is completed. By default 4 worker threads are devoted to this task.
