# -*- coding: utf-8 -*-

from distutils.core import setup

from setuptools import find_packages

classifiers = """
Development Status :: 3 - Alpha
Environment :: Console
License :: OSI Approved :: GNU General Public License v3 or later (GPLv3+)
Intended Audience :: Science/Research
Topic :: Scientific/Engineering
Topic :: Scientific/Engineering :: Bio-Informatics
Programming Language :: Python :: 3.7
Operating System :: POSIX :: Linux
""".strip().split('\n')

setup(
    name='bulk_upload_to_library.py',
    version='0.0.2',
    scripts=['bulk_upload_to_library.py'],
    url='https://github.com/pvanheus/galaxy_bulk_upload_from_server',
    license='GPLv3',
    author='Peter van Heusden',
    author_email='pvh@sanbi.ac.za',
    description='Bulk upload FASTQ files from server to Galaxy.',
    keywords='bioinformatics galaxy',
    classifiers=classifiers,
    install_requires=[
        'bioblend>=0.12.0',
        'PyYAML>=5.1.1',
        'tqdm>=4.32.2'
    ]
)