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

import contextlib
import csv
import io
import json
import os
import runpy
import shutil
import site
import sys
import sysconfig
import unittest
from email.parser import Parser
from os.path import dirname, join as jp, exists
from subprocess import check_call, check_output, STDOUT
from tempfile import TemporaryDirectory
from unittest import mock
from zipfile import ZipFile

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

from wheel_axle.runtime.constants import AXLE_DONE_FILE, AXLE_LOCK_FILE, SYMLINKS_FILE

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

# How `karellen-llvm` builds its platform-specific but Python-agnostic wheels
NOT_PURE_SETUP_CFG = "\n".join(["[bdist_wheel]",
                                "root_is_pure = false",
                                "python_tag = py3",
                                "abi_tag = none", ""])


class BuildAxleTest(unittest.TestCase):
    def is_success(self):
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

    def build_pep517(self, dir_name, setup_cfg=None):
        """Builds the way `pip install <source tree>` does, through the PEP 517 hooks.

        This is not the same code path as `setup.py bdist_axle`. The frontend asks for
        the metadata first, which runs `dist_info` and therefore `egg2dist` on its own,
        outside of `bdist_axle.run()`, and then hands the resulting `.dist-info` back to
        the wheel build to be reused verbatim.

        A frontend cannot pass command options through, so `setup_cfg`, if given, is
        written out as the project's `setup.cfg` to configure the build instead.
        """
        src_dir = jp(self.test_dir, dir_name)
        shutil.copytree(src_dir, self.src_dir, symlinks=True, ignore_dangling_symlinks=True)
        if setup_cfg:
            with open(jp(self.src_dir, "setup.cfg"), "wt") as f:
                f.write(setup_cfg)

        # The build runs out-of-process and without isolation, so `wheel_axle` has to be
        # reachable from wherever this test itself imported it.
        env = dict(os.environ)
        env["PYTHONPATH"] = os.pathsep.join(path for path in sys.path if path)

        check_call([sys.executable, "-m", "pip", "wheel",
                    "--no-build-isolation", "--no-deps", "--no-index",
                    "--wheel-dir", self.dist_dir, self.src_dir], env=env)

        check_call(["twine", "check", "--strict", f"{self.dist_dir}/*.whl"])

    def read_symlinks(self, wheel_file, dist_name):
        with ZipFile(wheel_file) as wheel:
            contents = wheel.read(f"{dist_name}.dist-info/{SYMLINKS_FILE}").decode("utf-8")
        return {l[0]: (l[1], l[2]) for l in csv.reader(contents.splitlines())}

    def check_startup_files(self, wheel_file, dist_name, require_libpython=False):
        """Asserts the wheel carries both the `.pth` and the PEP 829 `.start` file.

        Both have to sit next to the `.dist-info` and be named after it, in the root of the
        wheel, because that is how the runtime finds the `.dist-info` from them. Anywhere
        else, such as `.data/purelib` of a wheel whose root is platlib, they can be
        installed into a different directory than the `.dist-info`.
        """
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
        self.assertEqual(pth, "import os, site, sys; _axle_site = os.path.dirname(fullname); "
                              "_axle_dir = _axle_site.split(os.sep); "
                              "_axle_lib = os.sep.join(_axle_dir[:-3] + ['lib'] + _axle_dir[-2:]); "
                              "_axle_add = _axle_dir[-3:-2] == [getattr(sys, 'platlibdir', 'lib')] != ['lib'] "
                              "and _axle_lib not in sys.path "
                              "and os.path.realpath(_axle_lib) != os.path.realpath(_axle_site); "
                              "_axle_len = len(sys.path); "
                              "_axle_add and sys.path.extend(site.getsitepackages()); "
                              "import wheel_axle.runtime; wheel_axle.runtime.finalize(fullname); "
                              "_axle_add and sys.path.__delitem__(slice(_axle_len, None))\n")

        self.check_runtime_dependency(metadata, require_libpython)

    def check_finalized(self, site_dir, dist_name):
        """Asserts the distribution installed into `site_dir` was finalized to completion,
        the last step of which is removing its startup files."""
        self.assertTrue(exists(jp(site_dir, f"{dist_name}.dist-info", AXLE_DONE_FILE)))
        self.assertFalse(exists(jp(site_dir, f"{dist_name}.pth")))
        self.assertFalse(exists(jp(site_dir, f"{dist_name}.start")))

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

    def test_pep517(self):
        """A wheel built through the PEP 517 hooks must be a complete Axle wheel.

        The metadata the frontend prepares up front is produced before `bdist_axle` is
        ever finalized and without an install tree to walk, so neither the runtime
        requirements nor the symlink table can come from there.
        """
        self.build_pep517("test_pep517")

        dist_name = "test_pep517-0.0.1"
        wheel_file = jp(self.dist_dir, f"{dist_name}-py3-none-any.whl")
        self.assertTrue(exists(wheel_file))
        self.check_startup_files(wheel_file, dist_name)

        with ZipFile(wheel_file) as wheel:
            self.assertIn(f"{dist_name}.dist-info/{AXLE_LOCK_FILE}", wheel.namelist())

        self.assertDictEqual(self.read_symlinks(wheel_file, dist_name), {
            "pep517lib/libfoo.so": ("libfoo.so.0", '0'),
            "pep517lib/libfoo.so.0": ("libfoo.so.0.1", '0'),
            f"{dist_name}.data/scripts/script2": ("script1", '0'),
        })

        self.install(wheel_file)

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
        self.check_startup_files(jp(self.dist_dir, wheel_name), "test_axle_1-0.0.1")

    def test_axle_1_root_is_not_pure_abi_none_python_tag(self):
        self.build_axle("test_axle_1", "--root-is-pure", "false", "--abi-tag", "none", "--python-tag", "py3")

        print(*os.listdir(self.dist_dir))
        wheel_name = f"test_axle_1-0.0.1-py3-none-{self.get_platform()}.whl"
        print(wheel_name)
        self.assertTrue(exists(jp(self.dist_dir, wheel_name)))
        self.check_startup_files(jp(self.dist_dir, wheel_name), "test_axle_1-0.0.1")

    def test_axle_1_root_is_not_pure_abi3(self):
        """An `abi3` override must not require `--py-limited-api`.

        Setuptools 84.2 consults `abi_tag` itself and insists on `py_limited_api` once it
        sees `abi3` there. The override is `bdist_axle`'s to apply, so the base class has
        to keep deriving its tag from the interpreter, as it did before.
        """
        impl = tags.interpreter_name() + tags.interpreter_version()
        self.build_axle("test_axle_1", "--root-is-pure", "false", "--abi-tag", "abi3", "--python-tag", impl)

        print(*os.listdir(self.dist_dir))
        wheel_name = f"test_axle_1-0.0.1-{impl}-abi3-{self.get_platform()}.whl"
        print(wheel_name)
        self.assertTrue(exists(jp(self.dist_dir, wheel_name)))
        self.check_startup_files(jp(self.dist_dir, wheel_name), "test_axle_1-0.0.1")

    def test_axle_1_build_number(self):
        """The startup files are named after the `.dist-info`, which a build tag is not part of.

        The runtime locates the `.dist-info` by stripping the suffix off the startup file
        being processed, so a startup file named after the wheel, build tag included,
        sends it looking for a `.dist-info` that does not exist.
        """
        self.build_axle("test_axle_1", "--build-number", "1")

        dist_name = "test_axle_1-0.0.1"
        wheel_file = jp(self.dist_dir, f"{dist_name}-1-py3-none-any.whl")
        self.assertTrue(exists(wheel_file))
        self.check_startup_files(wheel_file, dist_name)

        self.install(wheel_file)
        self.check_finalized(sysconfig.get_path("purelib"), dist_name)

    def test_pep517_setup_cfg_abi_none_python_tag(self):
        """Tags overridden from `setup.cfg`, the only way to reach a PEP 517 build.

        This is how `karellen-llvm` packages its platform-specific but Python-agnostic
        wheels, and it broke when setuptools 84.2 made `bdist_wheel.abi_tag` read-only.
        """
        self.build_pep517("test_pep517", setup_cfg=NOT_PURE_SETUP_CFG)

        dist_name = "test_pep517-0.0.1"
        print(*os.listdir(self.dist_dir))
        wheel_file = jp(self.dist_dir, f"{dist_name}-py3-none-{self.get_platform()}.whl")
        self.assertTrue(exists(wheel_file))
        self.check_startup_files(wheel_file, dist_name)

        with ZipFile(wheel_file) as wheel:
            self.assertIn(f"{dist_name}.dist-info/{AXLE_LOCK_FILE}", wheel.namelist())

    @unittest.skipIf(sys.version_info >= (3, 15), "Python 3.15+ runs the `.start` file instead")
    def test_pth_line_touches_sys_path_only_where_platlib_is_apart(self):
        """The `.pth` line extends `sys.path` only where the runtime cannot be reached yet.

        That is the case for a `.pth` in `<prefix>/lib64/...` whose `<prefix>/lib/...` is a
        different directory and not on `sys.path` yet. The runtime and what it imports,
        such as `pip`, may then be in `lib` of any prefix, so every site directory is made
        importable for the duration. Everywhere else `sys.path` must be left exactly as
        `site` has it.

        The line is run by `site.addpackage` itself, off a real `.pth` file, as it is the
        frame `site` executes it in that the line has to work in. `site.getsitepackages()`
        is replaced, since distributions patch it (Debian adds `dist-packages`).
        """
        # Not at the top of the module: `bdist_axle` imports `distutils` before `setuptools`
        # does, which on Python 3.11 loads the standard library's and breaks `setup()`
        from wheel_axle.bdist_axle import BdistAxle

        # `site` names the directories `<prefix>/<libdir>/pythonX.Y/site-packages`
        python_dir = os.path.basename(dirname(sysconfig.get_path("purelib")))

        def site_packages(libdir):
            path = jp(self.target_dir.name, libdir, python_dir, "site-packages")
            os.makedirs(path, exist_ok=True)
            return path

        lib = site_packages("lib")
        lib64 = site_packages("lib64")
        os.symlink("lib", jp(self.target_dir.name, "lib64link"))
        lib64link = jp(self.target_dir.name, "lib64link", python_dir, "site-packages")
        other = jp(self.target_dir.name, "other")
        # Fewer path components than `<prefix>/<libdir>/pythonX.Y/site-packages` has
        shallow = dirname(self.target_dir.name)
        site_dirs = [lib64, lib, jp(other, "lib")]

        cases = [
            # platlibdir (`None` predates it), `.pth` directory, `sys.path` when it runs, extended
            ("lib64", lib64, [other, lib64], True),
            ("lib64", lib64, [other, lib64, lib], False),
            ("lib64link", lib64link, [other, lib64link], False),
            ("lib64", lib, [other, lib64, lib], False),
            ("lib", lib, [other, lib], False),
            (None, lib64, [other, lib64], False),
            ("lib64", shallow, [other, shallow], False),
        ]
        for platlibdir, pth_dir, sys_path, extended in cases:
            with self.subTest(platlibdir=platlibdir, pth_dir=pth_dir, sys_path=sys_path):
                pth_name = f"{os.path.basename(self.target_dir.name)}.pth"
                with open(jp(pth_dir, pth_name), "w") as f:
                    f.write(BdistAxle.AXLE_PTH_CONTENTS + "\n")

                finalize_sys_paths = []
                stderr = io.StringIO()
                try:
                    with mock.patch.object(sys, "platlibdir", platlibdir or "lib"), \
                            mock.patch.object(sys, "path", list(sys_path)), \
                            mock.patch("site.getsitepackages", return_value=list(site_dirs)), \
                            mock.patch("wheel_axle.runtime.finalize",
                                       side_effect=lambda _: finalize_sys_paths.append(list(sys.path))), \
                            contextlib.redirect_stderr(stderr):
                        if platlibdir is None:
                            del sys.platlibdir
                        site.addpackage(pth_dir, pth_name, set())
                        sys_path_after = list(sys.path)
                finally:
                    os.unlink(jp(pth_dir, pth_name))

                self.assertEqual(stderr.getvalue(), "")
                self.assertEqual(finalize_sys_paths, [sys_path + site_dirs if extended else sys_path])
                self.assertEqual(sys_path_after, sys_path)

    @unittest.skipIf(sys.platlibdir == "lib", "platlib is purelib on this interpreter")
    def test_pep517_not_pure_platlib_apart_from_purelib(self):
        """A non-pure wheel finalizes where platlib and purelib are different directories.

        Its `.dist-info` and startup files go to platlib (`lib64`), while the runtime, a
        pure distribution, goes to purelib (`lib`). Before Python 3.15 an interpreter that
        is not a virtual environment adds `lib64` and runs its `.pth` files before `lib` is
        even on `sys.path`, so the `.pth` cannot import the runtime as it is. Nor is the
        runtime's own `pip` necessarily in that prefix: on Fedora a `pip install` goes to
        `/usr/local`, while `pip` itself is in `/usr/lib`, a site directory added later still.

        A virtual environment would hide this twice over: it symlinks `lib64` to `lib`, and
        its `site` processes the site directories twice. So `lib64` is made a directory of
        its own here, `pip` is moved to a second prefix, and the single pass of a system
        interpreter over both is replayed with `python -S` and `site.addsitepackages()`.
        """
        self.build_pep517("test_pep517", setup_cfg=NOT_PURE_SETUP_CFG)

        dist_name = "test_pep517-0.0.1"
        wheel_file = jp(self.dist_dir, f"{dist_name}-py3-none-{self.get_platform()}.whl")

        venv_dir = jp(self.target_dir.name, "venv")
        check_call([sys.executable, "-m", "venv", venv_dir])
        venv_python = jp(venv_dir, "bin", "python")
        lib64 = jp(venv_dir, sys.platlibdir)
        if os.path.islink(lib64):
            os.unlink(lib64)

        paths = json.loads(check_output([venv_python, "-S", "-c",
                                         "import json, sysconfig; print(json.dumps(sysconfig.get_paths()))"]))
        purelib, platlib = paths["purelib"], paths["platlib"]
        os.makedirs(platlib, exist_ok=True)
        self.assertNotEqual(os.path.realpath(purelib), os.path.realpath(platlib))

        # The runtime and its `filelock` go to purelib, as any installer would put them
        import filelock
        import wheel_axle.runtime
        shutil.copytree(dirname(wheel_axle.runtime.__file__), jp(purelib, "wheel_axle", "runtime"))
        shutil.copytree(dirname(filelock.__file__), jp(purelib, "filelock"))

        check_call([venv_python, "-m", "pip", "install", "--no-deps", "--no-index", wheel_file])
        self.assertTrue(exists(jp(platlib, f"{dist_name}.dist-info")))
        self.assertTrue(exists(jp(platlib, f"{dist_name}.pth")))
        self.assertTrue(exists(jp(purelib, "pep517lib", "libfoo.so.0.1")))

        # `pip`, which came with the virtual environment, moves to purelib of a second prefix
        other_prefix = jp(self.target_dir.name, "other")
        other_purelib = jp(other_prefix, "lib", os.path.basename(dirname(purelib)), "site-packages")
        os.makedirs(other_purelib)
        for name in os.listdir(purelib):
            if name == "pip" or name.startswith("pip-"):
                shutil.move(jp(purelib, name), jp(other_purelib, name))

        output = check_output([venv_python, "-S", "-c",
                               "import site, sys; site.PREFIXES[:] = [sys.prefix, sys.argv[1]]; "
                               "site.addsitepackages(set())", other_prefix],
                              stderr=STDOUT, text=True)
        print(output)
        self.assertNotIn("Error", output)

        self.check_finalized(platlib, dist_name)
        self.assertEqual(os.readlink(jp(purelib, "pep517lib", "libfoo.so")), "libfoo.so.0")
        self.assertEqual(os.readlink(jp(purelib, "pep517lib", "libfoo.so.0")), "libfoo.so.0.1")


if __name__ == "__main__":
    unittest.main()
