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
from email.parser import Parser
from os.path import dirname, join as jp, exists
from subprocess import check_call
from tempfile import TemporaryDirectory
from zipfile import ZipFile

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

try:
    # SetupTools >= 70.1
    from setuptools.command.bdist_wheel import get_abi_tag, get_platform, tags
except ImportError:
    try:
        # Wheel >= 0.44.0
        from wheel._bdist_wheel import get_abi_tag, get_platform, tags
    except ImportError:
        # Wheel < 0.44.0
        from wheel.bdist_wheel import get_abi_tag, get_platform, tags


class BuildAxleTest(unittest.TestCase):
    def is_success(self):
        if hasattr(self._outcome, 'errors'):
            # Python 3.4 - 3.10  (These two methods have no side effects)
            result = self.defaultTestResult()
            self._feedErrorsToResult(result, self._outcome.errors)
        else:
            # Python 3.11+
            result = self._outcome.result
        return all(test != self for test, text in result.errors + result.failures)

    def setUp(self) -> None:
        self.test_dir = jp(dirname(dirname(__file__)), "resources")
        self.target_dir = TemporaryDirectory(prefix="build_axle_tests")
        self.target_dir._finalizer.detach()  # to make cleanup conditional
        self.src_dir = jp(self.target_dir.name, "src")
        self.build_dir = jp(self.target_dir.name, "build")
        self.dist_dir = jp(self.target_dir.name, "dist")
        self.wheels = set()

    def tearDown(self) -> None:
        if self.is_success():
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

        check_call(["twine", "check", "--strict", f"{self.dist_dir}/*.whl"])

    def check_startup_files(self, wheel_file, dist_name, require_libpython=False):
        """Asserts the wheel carries both the `.pth` and the PEP 829 `.start` file."""
        with ZipFile(wheel_file) as wheel:
            names = wheel.namelist()
            self.assertIn(dist_name + ".pth", names)
            self.assertIn(dist_name + ".start", names)

            pth = wheel.read(dist_name + ".pth").decode("utf-8")
            start = wheel.read(dist_name + ".start").decode("utf-8")
            metadata = wheel.read(dist_name + ".dist-info/METADATA").decode("utf-8")

        self.assertEqual(start, "wheel_axle.runtime:start\n")

        # The `.pth` file keeps calling the legacy entry point. It is only ever executed
        # by the Pythons predating PEP 829, since 3.15 and later suppress the `import`
        # line of a `.pth` file that has a `.start` file of the same name next to it, and
        # `finalize` is the one entry point every published runtime provides.
        self.assertEqual(pth.strip(), "import wheel_axle.runtime; wheel_axle.runtime.finalize(fullname);")

        self.check_runtime_dependency(metadata, require_libpython)

    def check_runtime_dependency(self, metadata, require_libpython):
        """Asserts the `.start` floor is scoped to the Pythons that actually run `.start`.

        Wheel Axle Runtime 0.0.12 is the first release providing the `.start` entry point
        and the first one requiring Python 3.10. Demanding it unconditionally makes every
        wheel built here uninstallable on Python 3.9, so the floor has to be carried by an
        environment marker that only Python 3.15+ satisfies. Below that the `.pth` file
        drives the install and any published runtime will do.
        """
        requirements = [Requirement(value)
                        for key, value in Parser().parsestr(metadata).items()
                        if key == "Requires-Dist"]
        runtime_reqs = [req for req in requirements
                        if canonicalize_name(req.name) == "wheel-axle-runtime"]
        self.assertTrue(runtime_reqs, "no wheel-axle-runtime requirement in %r" % requirements)

        # `require_libpython` additionally rules out the runtimes predating that feature
        legacy_allowed = {"0.0.11", "0.0.12", "0.0.13"} if require_libpython \
            else {"0.0.5", "0.0.11", "0.0.12", "0.0.13"}
        expectations = [("3.9", legacy_allowed),
                        ("3.14", legacy_allowed),
                        ("3.15", {"0.0.12", "0.0.13"})]

        for python_version, allowed in expectations:
            with self.subTest(python_version=python_version):
                applicable = [req for req in runtime_reqs
                              if not req.marker or req.marker.evaluate({"python_version": python_version})]
                self.assertTrue(applicable, "nothing applies on Python %s" % python_version)

                for candidate in ("0.0.5", "0.0.11", "0.0.12", "0.0.13", "1.0"):
                    satisfied = all(candidate in req.specifier for req in applicable)
                    self.assertEqual(satisfied, candidate in allowed,
                                     "runtime %s on Python %s: expected %s, got %s" %
                                     (candidate, python_version, candidate in allowed, satisfied))

    def install(self, wheel_file, user=False, deps=[]):
        check_call([sys.executable, "-m", "pip", "install", "--pre"] +
                   (["--user", "--force-reinstall"] if user else []) +
                   [wheel_file] + deps)
        check_call([sys.executable, "-c", "import site"])
        self.wheels.add(wheel_file)

    def uninstall(self, wheel_file):
        check_call([sys.executable, "-m", "pip", "uninstall", "--yes", wheel_file])
        self.wheels.remove(wheel_file)

    def test_axle_1(self):
        self.build_axle("test_axle_1")

        wheel_file = jp(self.dist_dir, "test_axle_1-0.0.1-py3-none-any.whl")
        self.assertTrue(exists(wheel_file))
        self.check_startup_files(wheel_file, "test_axle_1-0.0.1")

        with open(jp(self.build_dir, "test_axle_1-0.0.1.dist-info", "symlinks.txt")) as f:
            reader = csv.reader(f)
            symlinks = {l[0]: (l[1], l[2]) for l in reader}

        self.assertFalse(exists(jp(self.build_dir, "test_axle_1-0.0.1.dist-info", "require-libpython")))

        self.assertDictEqual(symlinks, {
            "bar/foo.so": ("../../../foo.so", '0'),
            "test_axle_1-0.0.1.data/scripts/script2": ("script1", '0'),
            "test_axle_1-0.0.1.data/headers/header2.h": ("header1.h", '0'),
            "test_axle_1-0.0.1.data/data/lib/foo.so": ("foo.1.so", '0'),
        })

    def test_axle_2_with_libpython_req(self):
        self.build_axle("test_axle_2_libpython", "--require-libpython", "true")

        wheel_file = jp(self.dist_dir, "test_axle_2_libpython-0.0.1-py3-none-any.whl")
        self.assertTrue(exists(wheel_file))
        self.check_startup_files(wheel_file, "test_axle_2_libpython-0.0.1", require_libpython=True)

        with open(jp(self.build_dir, "test_axle_2_libpython-0.0.1.dist-info", "symlinks.txt")) as f:
            reader = csv.reader(f)
            symlinks = {l[0]: (l[1], l[2]) for l in reader}

        self.assertTrue(exists(jp(self.build_dir, "test_axle_2_libpython-0.0.1.dist-info", "require-libpython")))

        print(symlinks)
        self.assertDictEqual(symlinks, {
            "bar/foo.so": ("../../../foo.so", '0'),
            "test_axle_2_libpython-0.0.1.data/scripts/script2": ("script1", '0'),
            "test_axle_2_libpython-0.0.1.data/headers/header2.h": ("header1.h", '0'),
            "test_axle_2_libpython-0.0.1.data/data/lib/foo.so": ("foo.1.so", '0'),
        })

    def test_issue_12(self):
        self.build_axle("test_issue_12")

        wheel_file = jp(self.dist_dir, "test_issue_12-0.0.1-py3-none-any.whl")
        self.assertTrue(exists(wheel_file))
        self.check_startup_files(wheel_file, "test_issue_12-0.0.1")

        with open(jp(self.build_dir, "test_issue_12-0.0.1.dist-info", "symlinks.txt")) as f:
            reader = csv.reader(f)
            symlinks = {l[0]: (l[1], l[2]) for l in reader}

        self.assertDictEqual(symlinks, {
            "mypackage/lib/foo.so": ("foo.so.0", '0'),
            "mypackage/lib/foo.so.0": ("foo.so.0.1", '0'),
            "mypackage/lib/prefix/foo.so": ("foo.so.0", '0'),
            "mypackage/lib/prefix/foo.so.0": ("foo.so.0.1", '0'),
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
