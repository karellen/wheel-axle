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

import os
from distutils import dir_util, log
from distutils.errors import DistutilsFileError


def copy_link(src, dst, update=0, verbose=1, dry_run=0, reproduce_link=False):
    if os.path.isdir(dst):
        dir = dst
        dst = os.path.join(dst, os.path.basename(src))
    else:
        dir = os.path.dirname(dst)

    link_dest = os.readlink(src)
    link_dest_isdir = os.path.isdir(os.path.join(os.path.dirname(src), link_dest))

    if verbose >= 1:
        log.info("%s link %s (%s) -> %s",
                 "reproducing" if reproduce_link else "registering",
                 src,
                 link_dest,
                 dir if os.path.basename(dst) == os.path.basename(src) else dst)

    if reproduce_link:
        os.symlink(link_dest, dst, link_dest_isdir)

    return dst, link_dest, link_dest_isdir


def copy_tree(src, dst, preserve_mode=1, preserve_times=1,
              preserve_symlinks=0, update=0, verbose=1, dry_run=0):
    from distutils.file_util import copy_file

    if not dry_run and not os.path.isdir(src):
        raise DistutilsFileError(
            "cannot copy tree '%s': not a directory" % src)
    try:
        names = os.listdir(src)
    except OSError as e:
        if dry_run:
            names = []
        else:
            raise DistutilsFileError(
                "error listing files in '%s': %s" % (src, e.strerror))

    if not dry_run:
        dir_util.mkpath(dst, verbose=verbose)

    outputs = []
    links = []

    for n in names:
        src_name = os.path.join(src, n)
        dst_name = os.path.join(dst, n)

        if n.startswith('.nfs'):
            # skip NFS rename files
            continue

        if os.path.islink(src_name):
            link_dest = os.readlink(src_name)
            link_dest_isdir = os.path.isdir(os.path.join(os.path.dirname(src_name), link_dest))
            if verbose >= 1:
                log.info("registering link %s (%s) -> %s", src_name, link_dest, dst_name)
            links.append((dst_name, link_dest, link_dest_isdir))

        elif os.path.isdir(src_name):
            _outputs, _links = copy_tree(src_name, dst_name, preserve_mode,
                                         preserve_times, preserve_symlinks, update,
                                         verbose=verbose, dry_run=dry_run)
            outputs.extend(_outputs)
            links.extend(_links)
        else:
            copy_file(src_name, dst_name, preserve_mode,
                      preserve_times, update, verbose=verbose,
                      dry_run=dry_run)
            outputs.append(dst_name)

    return outputs, links
