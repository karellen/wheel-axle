#!/usr/bin/env python
#   -*- coding: utf-8 -*-

from os import walk
from os.path import abspath, dirname, join as jp

from setuptools import setup, find_packages

import wheel_axle.bdist_axle


def get_data_files(current_path=None, ignore_root=False):
    current_path = current_path or abspath(dirname(__file__))
    for root, dirs, files in walk(current_path, followlinks=True):
        if ignore_root and current_path == root:
            continue

        path_prefix = root[len(current_path) + 1:]
        yield path_prefix, [jp(root, f) for f in files]


def get_files(current_path=None, ignore_root=False):
    current_path = current_path or abspath(dirname(__file__))
    for root, dirs, files in walk(current_path, followlinks=True):
        if ignore_root and current_path == root:
            continue

        yield from (jp(root, f) for f in files)


name = "test-axle-1"

setup(
    name=name,
    version='0.0.1',
    description='Test Axle 1',
    long_description='Test Axle 1 Long Description\n',
    long_description_content_type='text/markdown',
    classifiers=[
        'Programming Language :: Python',
        'Operating System :: POSIX :: Linux',
        'Development Status :: 5 - Production/Stable',
        'Environment :: Console',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: Apache Software License',
        'Topic :: Software Development :: Build Tools',
    ],
    keywords='',
    author='Arcadiy Ivanov',
    author_email='arcadiy@karellen.co',
    maintainer='Arcadiy Ivanov',
    maintainer_email='arcadiy@karellen.co',

    license='Apache License, Version 2.0',

    url='https://karellen.co',
    project_urls={
        'Bug Tracker': 'https://github.com/karellen/axle-runtime/issues',
        'Documentation': 'https://github.com/karellen/axle-runtime',
        'Source Code': 'https://github.com/karellen/axle-runtime'
    },
    scripts=list(get_files("scripts")),
    packages=find_packages("src"),
    package_dir={"": "src"},
    data_files=list(get_data_files("data")),
    headers=list(get_files("headers")),
    package_data={"": ["*.so"]},
    install_requires=[],
    dependency_links=[],
    zip_safe=False,
    obsoletes=[],
    cmdclass={"bdist_axle": wheel_axle.bdist_axle.BdistAxle}
)
