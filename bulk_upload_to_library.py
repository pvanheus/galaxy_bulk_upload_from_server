#!/usr/bin/env python

import argparse
import asyncio
from dataclasses import dataclass
from enum import Enum
import json
import os
import os.path
import subprocess
import shlex
from pathlib import Path
from typing import List

import bioblend
from tqdm import tqdm


class CompressionType(Enum):
    GZIP = 1
    BZIP2 = 2
    NONE = 3


# taken from https://stackoverflow.com/questions/11415570/directory-path-types-with-argparse
class readable_dir(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        prospective_dir = values
        if not os.path.isdir(prospective_dir):
            raise argparse.ArgumentError(self, "readable_dir:{0} is not a valid path".format(prospective_dir))
        if os.access(prospective_dir, os.R_OK):
            setattr(namespace, self.dest, prospective_dir)
        else:
            raise argparse.ArgumentError(self, "readable_dir:{0} is not a readable dir".format(prospective_dir))


def safe_run(cmd_str: str, function_name: str) -> subprocess.CompletedProcess:
    cmd = shlex.split(cmd_str)
    proc = subprocess.run(cmd, capture_output=True)
    if proc.returncode:
        raise OSError(f"{function_name} failed: cmd_str {cmd_str} return code: {proc.returncode} stderr: {proc.stderr.decode('utf-8')}\n\nstdout: {proc.stdout.decode('utf-8')}")
    return proc


def create_library(name: str, parsec_cmd: str = 'parsec') -> str:
    cmd_str = f"{parsec_cmd} libraries create_library '{name}'"
    proc = safe_run(cmd_str, 'create_library')
    library_details = proc.stdout.decode('utf-8')
    library_id = json.loads(library_details)['id']
    return library_id


def rename_library_item(item_id: str, new_name: str, parsec_cmd: str = 'parsec') -> None:
    cmd_str = f"{parsec_cmd} libraries update_library_dataset --name '{new_name}' {item_id}"
    safe_run(cmd_str, 'rename_library_item')
    # nothing to return if there is no error


def detect_compression(path: Path) -> CompressionType:
    if path.open('rb').read(2) == b'\x1f\x8b':
        return CompressionType.GZIP
    elif path.open('rb').read(3) == b'BZh':
        return CompressionType.BZIP2
    else:
        return CompressionType.NONE


def wait_for_dataset(library_id: str, dataset_id: str, parsec_cmd: str = 'parsec') -> None:
    cmd_str = f'parsec libraries wait_for_dataset {library_id} {dataset_id}'
    safe_run(cmd_str, 'wait_for_dataset')


@dataclass
class rename_info:
    library_id: str
    dataset_id: str
    new_name: str


async def dataset_renamer(queue: asyncio.Queue, parsec_cmd: str = 'parsec') -> None:
    while True:
        (info) = await queue.get()
        # wait for Galaxy to process it before renaming it
        wait_for_dataset(info.library_id, info.dataset_id)
        rename_library_item(info.dataset_id, info.new_name, parsec_cmd)
        queue.task_done()


async def upload_datasets(datasets_path: Path, library_name: str, dbkey: str, num_workers: int = 2, parsec_cmd = 'parsec') -> None:
    queue = asyncio.Queue()
    workers = [asyncio.create_task(dataset_renamer(queue, parsec_cmd)) for _ in range(num_workers)]
    if not datasets_path.exists() or not datasets_path.is_dir():
        raise IOError(f'path {datasets_path} must be a directory')
    library_id = create_library(library_name, parsec_cmd)
    fastq_file: Path  # add type hint for fastq_file, it is a Path
    fastq_filenames: List[Path] = list(datasets_path.glob('**/*.fastq*'))
    for fastq_file in tqdm(fastq_filenames):
        compression_type = detect_compression(fastq_file)
        if compression_type == CompressionType.GZIP:
            format = 'fastqsanger.gz'
        elif compression_type == CompressionType.BZIP2:
            format = 'fastqsanger.bz2'
        elif compression_type == CompressionType.NONE:
            format = 'fastqsanger'
        else:
            raise ValueError(f'Unknown compression type {compression_type}')
        cmd_str = f"{parsec_cmd} libraries upload_file_from_local_path --file_type {format} --dbkey {dbkey} {library_id} '{fastq_file}'"
        dataset_name = fastq_file.name
        fastq_pos = dataset_name.find('.fastq')
        dataset_name = dataset_name[:fastq_pos]  # strip everything from .fastq onwards
        proc = safe_run(cmd_str, 'upload_datasets')
        upload_details = proc.stdout.decode('utf-8')
        # return from a successful upload is a single item list
        # like:
        #
        # [
        #    {
        #     "url": "/api/libraries/33b43b4e7093c91f/contents/c24141d7e4e77705",
        #     "name": "SRR1165236_1.fastq.gz",
        #     "id": "c24141d7e4e77705"
        #     }
        # ]
        upload_dataset_id = json.loads(upload_details)[0]['id']
        await queue.put(rename_info(library_id, upload_dataset_id, dataset_name))
    print("waiting on renaming to finish")
    await queue.join()
    for worker in workers:
        worker.cancel()
    # no need to return anything when we are done uploading


if __name__ == '__main__':
    parser = argparse.ArgumentParser('Upload a directory of fastq files to Galaxy using parsec')
    parser.add_argument('--dbkey', default='mycoTube_H37RV', help='Galaxy DBKey for genome used by these samples')
    parser.add_argument('--parsec_cmd', default='parsec', help='Command (with arguments) to run galaxy-parsec')
    parser.add_argument('library_name', help='Library name to create')
    parser.add_argument('datasets_path', action=readable_dir, help='Directory path containing fastq files to upload')
    args = parser.parse_args()
    asyncio.run(upload_datasets(Path(args.datasets_path), args.library_name, args.dbkey, 2, args.parsec_cmd))
