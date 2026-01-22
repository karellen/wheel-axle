# -*- coding: utf-8 -*-
#
# (C) Copyright 2021 Karellen, Inc. (https://www.karellen.co/)
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

from os import environ
from pybuilder.core import (use_plugin, init, Author, task, depends, dependents)

use_plugin("python.install_dependencies")
use_plugin("python.core")
use_plugin("python.integrationtest")
use_plugin("python.flake8")
use_plugin("python.coverage")
use_plugin("python.distutils")
use_plugin("python.pycharm")
use_plugin("python.coveralls")
use_plugin("copy_resources")
use_plugin("filter_resources")

name = "wheel_axle"
version = "0.0.12.dev"

summary = "Axle is Python wheel enhancement library"
authors = [Author("Karellen, Inc.", "supervisor@karellen.co")]
maintainers = [Author("Arcadiy Ivanov", "arcadiy@karellen.co")]
url = "https://github.com/karellen/wheel-axle"
urls = {
    "Bug Tracker": "https://github.com/karellen/wheel-axle/issues",
    "Source Code": "https://github.com/karellen/wheel-axle/",
    "Documentation": "https://github.com/karellen/wheel-axle/"
}
license = "Apache License, Version 2.0"

requires_python = ">=3.9"

default_task = ["analyze", "publish"]


@init(environments="ci")
def init_ci_dependencies(project):
    project.build_depends_on("setuptools", environ["SETUPTOOLS_VER"])
    project.build_depends_on("pip", environ["PIP_VER"])
    if "WHEEL_VER" in environ:
        project.build_depends_on("wheel", environ["WHEEL_VER"])
    default_task.append("install_ci_dependencies")


@task
@depends("install_dependencies")
@dependents("compile_sources")
def install_ci_dependencies(project):
    pass


@init
def set_properties(project):
    if "WHEEL_VER" not in environ:
        project.depends_on("wheel", ">=0.37.0")
    project.depends_on("wheel-axle-runtime", "<1.0,>0.0.5")
    project.build_depends_on("twine")

    project.set_property("coverage_break_build", False)
    project.set_property("cram_fail_if_no_tests", False)

    project.set_property("integrationtest_inherit_environment", True)

    project.set_property("copy_resources_target", "$dir_dist/wheel_axle/bdist_axle")
    project.get_property("copy_resources_glob").append("LICENSE")
    project.include_file("wheel_axle/bdist_axle", "LICENSE")
    project.set_property("filter_resources_target", "$dir_dist")
    project.get_property("filter_resources_glob").append("wheel_axle/bdist_axle/__init__.py")

    project.set_property("distutils_readme_description", True)
    project.set_property("distutils_description_overwrite", True)
    project.set_property("distutils_upload_skip_existing", True)
    project.set_property("distutils_setup_keywords", ["wheel", "packaging",
                                                      "setuptools", "bdist_wheel",
                                                      "symlink", "postinstall"])

    project.set_property("distutils_entry_points", {
        "distutils.commands": ["bdist_axle = wheel_axle.bdist_axle:BdistAxle"]
    })

    project.set_property("distutils_classifiers", [
        "License :: OSI Approved :: Apache Software License",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Programming Language :: Python :: 3.13",
        "Operating System :: MacOS :: MacOS X",
        "Operating System :: POSIX",
        "Operating System :: POSIX :: Linux",
        "Topic :: System :: Archiving :: Packaging",
        "Topic :: Software Development :: Build Tools",
        "Intended Audience :: Developers",
        "Development Status :: 4 - Beta"
    ])
