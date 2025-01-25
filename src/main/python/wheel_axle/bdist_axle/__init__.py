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

import contextlib
import itertools
import os
import stat
import warnings
from distutils.cmd import Command
from distutils.command.build_scripts import build_scripts
from distutils.command.install_data import install_data
from distutils.command.install_headers import install_headers
from distutils.util import convert_path
from glob import glob

from setuptools.command.build_py import build_py
from setuptools.command.egg_info import egg_info, manifest_maker, FileList
from setuptools.command.install import install
from setuptools.command.install_lib import install_lib
from setuptools.command.install_scripts import install_scripts

try:
    # SetupTools >= 70.1
    from setuptools.command.bdist_wheel import bdist_wheel as _bdist_wheel, python_tag
except ImportError as e:
    try:
        # Wheel >= 0.44.0
        from wheel._bdist_wheel import bdist_wheel as _bdist_wheel, python_tag
    except ImportError:
        # Wheel < 0.44.0
        try:
            from wheel.bdist_wheel import bdist_wheel as _bdist_wheel, python_tag
        except ImportError:
            raise ImportError("Either `setuptools>=70.1` package or `wheel` package is required")

from wheel.vendored.packaging import tags

from wheel_axle.bdist_axle._file_utils import copy_link, copy_tree
from wheel_axle.runtime._symlinks import write_symlinks_file
from wheel_axle.runtime.constants import AXLE_LOCK_FILE, SYMLINKS_FILE, REQUIRE_LIBPYTHON_FILE

__version__ = "${dist_version}"
WHEEL_AXLE_DEPENDENCY = "wheel-axle-runtime<1.0"
WHEEL_AXLE_REQUIRE_LIBPYTHON_DEPENDENCY = f"{WHEEL_AXLE_DEPENDENCY},>0.0.5"

class SymlinkAwareCommmand(Command):
    def initialize_options(self):
        super().initialize_options()
        self._symlinks = []

    def copy_file(self, infile, outfile, preserve_mode=1, preserve_times=1,
                  link=None, level=1):
        """Copy a file respecting verbose, dry-run and force flags.  (The
        former two default to whatever is in the Distribution object, and
        the latter defaults to false for commands that don't define it.)"""

        if os.path.islink(infile):
            out = copy_link(infile, outfile, not self.force, dry_run=self.dry_run)
            self._symlinks.append(out)
            return out[0], 0

        return super().copy_file(infile, outfile, preserve_mode=preserve_mode, preserve_times=preserve_times,
                                 link=link,
                                 level=level)

    def copy_tree(self, infile, outfile, preserve_mode=1, preserve_times=1,
                  preserve_symlinks=0, level=1):
        """Copy an entire directory tree respecting verbose, dry-run,
        and force flags.
        """

        output, symlinks = copy_tree(infile, outfile, preserve_mode,
                                     preserve_times, preserve_symlinks,
                                     not self.force, dry_run=self.dry_run)
        self._symlinks.extend(symlinks)
        return output

    def get_symlinks(self):
        return self._symlinks


class InstallData(SymlinkAwareCommmand, install_data):
    def run(self):
        super().run()
        symlinks = set(self.get_symlinks())
        outfiles = list(self.outfiles)
        for idx, f in enumerate(outfiles):
            if f in symlinks:
                del self.outfiles[idx]


class InstallLib(SymlinkAwareCommmand, install_lib):
    def copy_tree(
            self, infile, outfile,
            preserve_mode=1, preserve_times=1, preserve_symlinks=0, level=1
    ):
        assert preserve_mode and preserve_times and not preserve_symlinks
        exclude = self.get_exclusions()

        if not exclude:
            return super().copy_tree(infile, outfile)

        # Exclude namespace package __init__.py* files from the output

        from setuptools.archive_util import unpack_directory
        from distutils import log

        outfiles = []

        def pf(src, dst):
            if dst in exclude:
                log.warn("Skipping installation of %s (namespace package)",
                         dst)
                return False

            if os.path.islink(src):
                link_dest = os.readlink(src)
                link_dest_isdir = os.path.isdir(os.path.join(os.path.dirname(src), link_dest))
                log.info("registering link %s (%s) -> %s", src, link_dest, dst)
                self._symlinks.append((dst, link_dest, link_dest_isdir))
                return False
            else:
                log.info("copying %s -> %s", src, os.path.dirname(dst))
                outfiles.append(dst)
                return dst

        unpack_directory(infile, outfile, pf)
        return outfiles

    def get_symlinks(self):
        symlinks = super().get_symlinks()
        exclude = self.get_exclusions()
        if exclude:
            return [f for f in symlinks if f[0] not in exclude]
        return symlinks


class InstallHeaders(SymlinkAwareCommmand, install_headers):
    pass


class InstallScripts(SymlinkAwareCommmand, install_scripts):
    pass


class BuildPy(build_py):
    def make_writable(self, target):
        if os.path.isfile(target):
            os.chmod(target, os.stat(target).st_mode | stat.S_IWRITE)

    def _get_package_data_output_mapping(self):
        yielded = set()
        for package, src_dir, build_dir, filenames in self.data_files:
            for filename in filenames:
                target = os.path.join(build_dir, filename)
                srcfile = os.path.join(src_dir, filename)
                key = target, srcfile
                if key not in yielded:
                    yielded.add(key)
                    yield key

    def build_package_data(self):
        """Copy data files into build directory"""
        for target, srcfile in self._get_package_data_output_mapping():
            self.mkpath(os.path.dirname(target))
            _outf, _copied = self.copy_file(srcfile, target)
            self.make_writable(target)

    def copy_file(self, infile, outfile, preserve_mode=1, preserve_times=1,
                  link=None, level=1):
        """Copy a file respecting verbose, dry-run and force flags.  (The
        former two default to whatever is in the Distribution object, and
        the latter defaults to false for commands that don't define it.)"""

        if os.path.islink(infile):
            out = copy_link(infile, outfile, not self.force, dry_run=self.dry_run, reproduce_link=True)
            return out[0], 1

        return super().copy_file(infile, outfile, preserve_mode=preserve_mode, preserve_times=preserve_times,
                                 link=link,
                                 level=level)

    def find_data_files(self, package, src_dir):
        """Return filenames for package's data files in 'src_dir'"""
        patterns = self._get_platform_patterns(
            self.package_data,
            package,
            src_dir,
        )
        globs_expanded = map(glob, patterns)
        # flatten the expanded globs into an iterable of matches
        globs_matches = itertools.chain.from_iterable(globs_expanded)
        glob_files = filter(lambda x: os.path.isfile(x) or os.path.islink(x), globs_matches)
        files = itertools.chain(
            self.manifest_files.get(package, []),
            glob_files,
        )
        return self.exclude_data_files(package, src_dir, files)


class EggInfo(SymlinkAwareCommmand, egg_info):
    def find_sources(self):
        """Generate SOURCES.txt manifest file"""
        manifest_filename = os.path.join(self.egg_info, "SOURCES.txt")
        mm = ManifestMaker(self.distribution)
        mm.manifest = manifest_filename
        mm.run()
        self.filelist = mm.filelist


class ManifestMaker(manifest_maker):
    def run(self):
        self.filelist = SymlinkAwareFileList()
        if not os.path.exists(self.manifest):
            self.write_manifest()  # it must exist so it'll get in the list
        self.add_defaults()
        if os.path.exists(self.template):
            self.read_template()
        self.add_license_files()
        self.prune_file_list()
        self.filelist.sort()
        self.filelist.remove_duplicates()
        self.write_manifest()


class SymlinkAwareFileList(FileList):
    def _safe_path(self, path):
        if os.path.islink(path):
            return True
        else:
            return super()._safe_path(path)


class BuildScripts(SymlinkAwareCommmand, build_scripts):
    def copy_scripts(self):
        scripts = list(self.scripts)
        self.scripts.clear()
        symlinks = []
        for script in scripts:
            script = convert_path(script)
            if os.path.exists(script) and os.path.islink(script):
                link_dest = os.readlink(script)
                link_dest_isdir = os.path.isdir(os.path.join(os.path.dirname(script), link_dest))
                outfile = os.path.join(self.build_dir, os.path.basename(script))
                symlinks.append((link_dest, outfile, link_dest_isdir))
            else:
                self.scripts.append(script)
        try:
            outfiles, updated_files = super().copy_scripts()
            for link_dest, outfile, link_dest_isdir in symlinks:
                if os.path.exists(outfile):
                    os.unlink(outfile)
                os.symlink(link_dest, outfile, link_dest_isdir)
                outfiles.append(outfile)
            return outfiles, updated_files
        finally:
            self.scripts.clear()
            self.scripts.extend(scripts)


class Install(install):
    def get_symlinks(self):
        """Assembles the symlinks of all the sub-commands."""
        symlinks = []
        for cmd_name in self.get_sub_commands():
            cmd = self.get_finalized_command(cmd_name)

            try:
                for filename in cmd.get_symlinks():
                    if filename not in symlinks:
                        symlinks.append(filename)
            except AttributeError:
                pass

        return symlinks

    def initialize_options(self):
        super().initialize_options()

    def finalize_options(self):
        super().finalize_options()
        self._restore_install_lib()

    def _restore_install_lib(self):
        """
        Undo secondary effect of `extra_path` adding to `install_lib`
        """
        suffix = os.path.relpath(self.install_lib, self.install_libbase)

        if suffix.strip() == BdistAxle.AXLE_PTH_CONTENTS.strip():
            self.install_lib = self.install_libbase

    def run(self):
        super().run()


@contextlib.contextmanager
def suppress_known_deprecation():
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", "setup.py install is deprecated")
        yield


class BdistAxle(_bdist_wheel):
    user_options = list(_bdist_wheel.user_options)
    user_options += [("root-is-pure=", None,
                      "set to manually override whether the wheel is pure "
                      "(default: None)"),
                     ("abi-tag=", None,
                      "set to override ABI tag "
                      "(default: None)"),
                     ("require-libpython=", None,
                      "set to indicate the package requires libpython in the exec_prefix/platlib",
                      "(default: False)")
                     ]

    boolean_options = list(_bdist_wheel.boolean_options)
    boolean_options += ["root-is-pure", "require-libpython"]

    AXLE_PTH_CONTENTS = """import wheel_axle.runtime; wheel_axle.runtime.finalize(fullname);"""

    def initialize_options(self):
        super().initialize_options()
        self.abi_tag = None
        self.abi_tag_supplied = False
        self.python_tag = None
        self.python_tag_supplied = False
        self.require_libpython = False

    def finalize_options(self):
        root_is_pure_supplied = self.root_is_pure is not None
        root_is_pure = self.root_is_pure
        self.abi_tag_supplied = self.abi_tag is not None

        self.python_tag_supplied = self.python_tag is not None
        if not self.python_tag_supplied:
            self.python_tag = python_tag()

        super().finalize_options()

        if root_is_pure_supplied:
            self.root_is_pure = bool(root_is_pure)

        if self.require_libpython:
            self.distribution.install_requires.append(WHEEL_AXLE_REQUIRE_LIBPYTHON_DEPENDENCY)
        else:
            self.distribution.install_requires.append(WHEEL_AXLE_DEPENDENCY)
        self.distribution.extra_path = self.wheel_dist_name, self.AXLE_PTH_CONTENTS

    def get_tag(self):
        tag = super().get_tag()

        tag = (self.python_tag if self.python_tag_supplied else tag[0],
               self.abi_tag if self.abi_tag_supplied else tag[1],
               tag[2])

        supported_tags = [(t.interpreter, t.abi, tag[2])
                          for t in tags.sys_tags()]
        assert tag in supported_tags, "would build wheel with unsupported tag {}".format(tag)
        return tag

    def run(self):
        with suppress_known_deprecation():
            def remove_patched_command_objs():
                for k in patch_classes:
                    if k in self.distribution.command_obj:
                        del self.distribution.command_obj[k]

            patch_classes = {"install_data": InstallData,
                             "install_lib": InstallLib,
                             "install_headers": InstallHeaders,
                             "install_scripts": InstallScripts,
                             "build_scripts": BuildScripts,
                             "build_py": BuildPy,
                             "egg_info": EggInfo,
                             "install": Install}

            old_cmdclass = dict(self.distribution.cmdclass)
            self.distribution.cmdclass.update(patch_classes)

            remove_patched_command_objs()
            try:
                super().run()
            finally:
                self.distribution.cmdclass = old_cmdclass
                remove_patched_command_objs()

    def egg2dist(self, egginfo_path, distinfo_path):
        super().egg2dist(egginfo_path, distinfo_path)

        install_cmd = self.get_finalized_command("install")

        symlinks = [(os.path.relpath(symlink[0], self.bdist_dir),
                     symlink[1],
                     symlink[2]) for symlink in install_cmd.get_symlinks()]
        write_symlinks_file(os.path.join(distinfo_path, SYMLINKS_FILE), symlinks)

        with open(os.path.join(distinfo_path, AXLE_LOCK_FILE), "wb"):
            pass

        if self.require_libpython:
            with open(os.path.join(distinfo_path, REQUIRE_LIBPYTHON_FILE), "wb"):
                pass

    def write_wheelfile(self, wheelfile_base, generator="bdist_axle (" + __version__ + ")"):
        return super().write_wheelfile(wheelfile_base, generator)
