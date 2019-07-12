FROM python:3.7
LABEL maintainer="Peter van Heusden <pvh@sanbi.ac.za>"

RUN mkdir /work
WORKDIR /work
ADD bulk_upload_to_library.py setup.py /work/
RUN python -m pip install .

ENTRYPOINT bulk_upload_to_library.py