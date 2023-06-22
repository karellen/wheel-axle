#!/usr/bin/env python
#   -*- coding: utf-8 -*-

from setuptools import setup

import wheel_axle.bdist_axle

name = "test-issue-12"

setup(
    name=name,
    version='0.0.1',
    description='Test Issue #12',
    long_description='Test Issue #12 Long Description\n',
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
        'Bug Tracker': 'https://github.com/karellen/wheel-axle/issues',
        'Documentation': 'https://github.com/karellen/wheel-axle',
        'Source Code': 'https://github.com/karellen/wheel-axle'
    },
    include_package_data=True,
    package_dir={
        "mypackage/lib": "cmake_install/cpp_libs",
    },
    package_data={
        "mypackage/lib": ["*.so*", "**/*.so*"],
    },
    install_requires=[],
    dependency_links=[],
    zip_safe=False,
    obsoletes=[],
    cmdclass={"bdist_axle": wheel_axle.bdist_axle.BdistAxle}
)
