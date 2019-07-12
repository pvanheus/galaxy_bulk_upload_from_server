#!/usr/bin/env python

import argparse
import asyncio
from dataclasses import dataclass
from enum import Enum
import json
import os
import os.path
from pathlib import Path
import shlex
import subprocess
import sys
from typing import List

from bioblend.galaxy import GalaxyInstance
from tqdm import tqdm
import yaml


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


def create_library(name: str, gi: GalaxyInstance) -> str:
    library_info = gi.libraries.create_library(name)
    library_id = library_info['id']
    return library_id


def detect_compression(path: Path) -> CompressionType:
    if path.open('rb').read(2) == b'\x1f\x8b':
        return CompressionType.GZIP
    elif path.open('rb').read(3) == b'BZh':
        return CompressionType.BZIP2
    else:
        return CompressionType.NONE


@dataclass
class rename_info:
    library_id: str
    dataset_id: str
    new_name: str


async def dataset_renamer(queue: asyncio.Queue, gi: GalaxyInstance) -> None:
    while True:
        (info) = await queue.get()
        # wait for Galaxy to process it before renaming it
        gi.libraries.wait_for_dataset(info.library_id, info.dataset_id)
        gi.libraries.update_library_dataset(info.dataset_id, name=info.new_name)
        queue.task_done()


async def upload_datasets(datasets_path: Path, library_name: str, dbkey: str, gi: GalaxyInstance, num_workers: int = 2) -> None:
    queue = asyncio.Queue()
    workers = [asyncio.create_task(dataset_renamer(queue, gi)) for _ in range(num_workers)]
    if not datasets_path.exists() or not datasets_path.is_dir():
        raise IOError(f'path {datasets_path} must be a directory')
    library_id = create_library(library_name, gi)
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
        upload_details = gi.libraries.upload_file_from_local_path(library_id, fastq_file, file_type=format, dbkey=dbkey)
        dataset_name = fastq_file.name
        fastq_pos = dataset_name.find('.fastq')
        dataset_name = dataset_name[:fastq_pos]  # strip everything from .fastq onwards
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
        upload_dataset_id = upload_details[0]['id']
        await queue.put(rename_info(library_id, upload_dataset_id, dataset_name))
    print("waiting on renaming to finish")
    await queue.join()
    for worker in workers:
        worker.cancel()
    # no need to return anything when we are done uploading


def get_galaxy_instance(args: argparse.Namespace) -> GalaxyInstance:
    if args.parsec_galaxy_instance:
        parsec_config_path = Path(Path.home(), '.parsec.yml')
        if not parsec_config_path.exists() or not parsec_config_path.is_file():
            raise IOError(f'parsec config file {parsec_config_path} not found')
        parsec_config = yaml.load(parsec_config_path.open(), Loader=yaml.Loader)
        if args.parsec_galaxy_instance == 'default':
            if '__default' not in parsec_config:
                raise IOError('default Galaxy instance requested from parsec config, but __default key missing')
            args.parsec_galaxy_instance = parsec_config['__default']
        if args.parsec_galaxy_instance not in parsec_config:
            raise IOError(f'{args.parsec_galaxy_instance} not found in parsec config')
        galaxy_key = parsec_config[args.parsec_galaxy_instance]['key']
        galaxy_url = parsec_config[args.parsec_galaxy_instance]['url']
    else:
        galaxy_key = args.galaxy_key
        galaxy_url = args.galaxy_url
    gi = GalaxyInstance(galaxy_url, key=galaxy_key)
    return gi


if __name__ == '__main__':
    parser = argparse.ArgumentParser('Upload a directory of fastq files to Galaxy using parsec')
    parser.add_argument('--dbkey', default='mycoTube_H37RV', help='Galaxy DBKey for genome used by these samples')
    parser.add_argument('--parsec_galaxy_instance', help='Galaxy instance in parsec configuration to load access details from (use "default" for default instance')
    parser.add_argument('--galaxy_url', help='URL of Galaxy storage')
    parser.add_argument('--galaxy_key', help='Galaxy API key')
    parser.add_argument('--num_renaming_workers', type=int, default=4, help='Number of worker processes for the renaming step')
    parser.add_argument('library_name', help='Library name to create')
    parser.add_argument('datasets_path', action=readable_dir, help='Directory path containing fastq files to upload')
    args = parser.parse_args()
    if args.parsec_galaxy_instance and (args.galaxy_key or args.galaxy_url):
        # got two mutually exclusive args
        parser.print_usage(file=sys.stderr)
        print('One of --parsec_galaxy_instance and --galaxy_url / --galaxy_key is required, not both', file=sys.stderr)
        sys.exit(1)
    if not args.parsec_galaxy_instance and not (args.galaxy_key and args.galaxy_url):
        # got none of the required arguments
        parser.print_usage(file=sys.stderr)
        print('Either --parsec_galaxy_instance or both --galaxy_url and --galaxy_key must be supplied')
        sys.exit(1)
    gi = get_galaxy_instance(args)
    asyncio.run(upload_datasets(Path(args.datasets_path), args.library_name, args.dbkey, gi, num_workers=args.num_renaming_workers))
