# -*- coding: utf-8 -*-
#
# (C) Copyright 2022 Karellen, Inc. (https://www.karellen.co/)
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

import csv
import os
import runpy
import shutil
import sys
import unittest
from os.path import dirname, join as jp, exists
from subprocess import check_call
from tempfile import TemporaryDirectory

from wheel.bdist_wheel import get_abi_tag, get_platform, tags


class BuildAxleTest(unittest.TestCase):
    def setUp(self) -> None:
        self.test_dir = jp(dirname(dirname(__file__)), "resources")
        self.target_dir = TemporaryDirectory()
        self.src_dir = jp(self.target_dir.name, "src")
        self.build_dir = jp(self.target_dir.name, "build")
        self.dist_dir = jp(self.target_dir.name, "dist")
        self.wheels = set()

    def tearDown(self) -> None:
        self.target_dir.cleanup()
        for wheel_file in list(self.wheels):
            try:
                self.uninstall(wheel_file)
            except Exception:
                sys.excepthook(*sys.exc_info())

    def build_axle(self, dir_name, *extra_args):
        src_dir = jp(self.test_dir, dir_name)
        shutil.copytree(src_dir, self.src_dir, symlinks=True, ignore_dangling_symlinks=True)

        old_sys_argv = list(sys.argv)
        old_cwd = os.getcwd()
        try:
            script_path = jp(self.src_dir, "setup.py")
            sys.argv.clear()
            sys.argv.extend([script_path, "bdist_axle",
                             "-k",
                             "--bdist-dir", self.build_dir,
                             "--dist-dir", self.dist_dir] + list(extra_args))
            os.chdir(self.src_dir)
            runpy.run_path(script_path)
        finally:
            os.chdir(old_cwd)
            sys.argv.clear()
            sys.argv.extend(old_sys_argv)

    def install(self, wheel_file, user=False, deps=[]):
        check_call([sys.executable, "-m", "pip", "install", "--pre"] +
                   (["--user", "--force-reinstall"] if user else []) +
                   [wheel_file] + deps)
        self.wheels.add(wheel_file)

    def uninstall(self, wheel_file):
        check_call([sys.executable, "-m", "pip", "uninstall", "--yes", wheel_file])
        self.wheels.remove(wheel_file)

    def test_axle_1(self):
        self.build_axle("test_axle_1")

        self.assertTrue(exists(jp(self.dist_dir, "test_axle_1-0.0.1-py3-none-any.whl")))

        with open(jp(self.build_dir, "test_axle_1-0.0.1.dist-info", "symlinks.txt")) as f:
            reader = csv.reader(f)
            symlinks = {l[0]: (l[1], l[2]) for l in reader}

        self.assertDictEqual(symlinks, {
            "bar/foo.so": ("../../../foo.so", '0'),
            "test_axle_1-0.0.1.data/scripts/script2": ("script1", '0'),
            "test_axle_1-0.0.1.data/headers/header2.h": ("header1.h", '0'),
            "test_axle_1-0.0.1.data/data/lib/foo.so": ("foo.1.so", '0'),
        })

    def get_platform(self):
        return get_platform(self.build_dir).lower().replace('-', '_').replace('.', '_')

    def test_axle_1_python_tag(self):
        self.build_axle("test_axle_1", "--python-tag", "py3")

        wheel_file = jp(self.dist_dir, "test_axle_1-0.0.1-py3-none-any.whl")
        self.assertTrue(exists(wheel_file))

        self.install(wheel_file)

    def test_axle_1_root_is_not_pure(self):
        self.build_axle("test_axle_1", "--root-is-pure", "false")

        print(*os.listdir(self.dist_dir))

        impl_name = tags.interpreter_name()
        impl_ver = tags.interpreter_version()
        impl = impl_name + impl_ver
        wheel_name = f"test_axle_1-0.0.1-{impl}-{get_abi_tag()}-{self.get_platform()}.whl"
        print(wheel_name)
        self.assertTrue(exists(jp(self.dist_dir, wheel_name)))

    def test_axle_1_root_is_not_pure_abi_none_python_tag(self):
        self.build_axle("test_axle_1", "--root-is-pure", "false", "--abi-tag", "none", "--python-tag", "py3")

        print(*os.listdir(self.dist_dir))
        wheel_name = f"test_axle_1-0.0.1-py3-none-{self.get_platform()}.whl"
        print(wheel_name)
        self.assertTrue(exists(jp(self.dist_dir, wheel_name)))


if __name__ == "__main__":
    unittest.main()
