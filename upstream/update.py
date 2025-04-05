#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
"""Update to a new upstream release."""
import argparse
import contextlib
import json
import logging
import re
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from itertools import accumulate
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Generator, List, Optional, Set, Tuple, TypedDict

import yaml
from kustomize.commands.build import build as kustomize_build
from semver import VersionInfo

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)
GH_REPO = "https://api.github.com/repos/{repo}"
GH_TAGS = "https://api.github.com/repos/{repo}/tags"
GH_BRANCH = "https://api.github.com/repos/{repo}/branches/{branch}"
GH_COMMIT = "https://api.github.com/repos/{repo}/commits/{sha}"
GH_PATH = "https://github.com/{repo}/{path}/?ref={branch}"

SOURCES = dict(
    cloud_storage=dict(
        repo="kubernetes-sigs/gcp-compute-persistent-disk-csi-driver",
        assembled="kustomized.yaml",
        release_tags=True,
        path="deploy/kubernetes/overlays/stable-master",
        version_parser=VersionInfo.parse,
        minimum="v1.3.0",
        maximum="v999.0.0",
    ),
)
FILEDIR = Path(__file__).parent
VERSION_RE = re.compile(r"^v\d+\.\d+")
IMG_RE = re.compile(r"^\s+image:\s+(\S+)")


@dataclass(frozen=True)
class Registry:
    """Object to define how to contact a Registry."""

    name: str
    path: str
    user: str
    pass_file: str

    @property
    def creds(self) -> "SyncCreds":
        """Get credentials as a SyncCreds Dict."""
        return {
            "registry": self.name,
            "user": self.user,
            "pass": Path(self.pass_file).read_text().strip(),
        }


@dataclass
class Release:
    """Defines a release type."""

    name: str
    path: str

    def __hash__(self) -> int:
        """Unique based on its name."""
        return hash(self.name)

    def __eq__(self, other) -> bool:
        """Comparable based on its name."""
        return isinstance(other, Release) and self.name == other.name

    def __lt__(self, other) -> bool:
        """Compare version numbers."""
        a, b = (
            self.name[1:],
            other.name[1:],
        )
        return VersionInfo.parse(a) < VersionInfo.parse(b)


SyncAsset = TypedDict("SyncAsset", {"source": str, "target": str, "type": str})
SyncCreds = TypedDict("SyncCreds", {"registry": str, "user": str, "pass": str})


class SyncConfig(TypedDict):
    """Type definition for building sync config."""

    version: int
    creds: List[SyncCreds]
    sync: List[SyncAsset]


def sync_asset(image: str, registry: Registry):
    """Factory for generating SyncAssets."""
    _, tag = image.split("/", 1)
    dest = f"{registry.name}/{registry.path.strip('/')}/{tag}"
    return SyncAsset(source=image, target=dest, type="image")


def main(source: str, registry: Optional[Registry]):
    """Main update logic."""
    local_releases = gather_current(source)
    gh_releases = gather_releases(source)
    new_releases = gh_releases - local_releases
    for release in new_releases:
        local_releases.add(download(source, release))
    unique_releases = list(dict.fromkeys(accumulate((sorted(local_releases)), dedupe)))
    all_images = set(image for release in unique_releases for image in images(release))
    if registry:
        mirror_image(all_images, registry)
    return unique_releases[-1].name, all_images


def gather_releases(source: str) -> Tuple[str, Set[Release]]:
    """Fetch from github the release manifests by version."""
    context = dict(**SOURCES[source])
    version_parser = context["version_parser"]
    if context.get("release_tags"):
        with urllib.request.urlopen(GH_TAGS.format(**context)) as resp:
            releases = sorted(
                [
                    Release(item["name"], GH_PATH.format(branch=item["name"], rel="", **context))
                    for item in json.load(resp)
                    if (
                        VERSION_RE.match(item["name"])
                        and not version_parser(item["name"][1:]).prerelease
                        and (
                            version_parser(context["minimum"][1:])
                            <= version_parser(item["name"][1:])
                            < version_parser(context["maximum"][1:])
                        )
                    )
                ],
                key=lambda r: version_parser(r.name[1:]),
                reverse=True,
            )

    return set(releases)


def gather_current(source: str) -> Set[Release]:
    """Gather currently supported manifests by the charm."""
    manifests = SOURCES[source]["assembled"]
    releases = dict()
    for release_path in (FILEDIR / source / "manifests").glob("*/*.yaml"):
        if release_path.name in manifests:
            releases[release_path.parent.name] = release_path
    return set(Release(version, files) for version, files in releases.items())


@contextlib.contextmanager
def captured_io(filepath: Path):
    """Redirect stdout to a file."""
    _stdout = sys.stdout
    sys.stdout = captured_file = filepath.open("w")
    captured_file.write("# ")  # comments out the first line
    yield
    captured_file.close()
    sys.stdout = _stdout


def download(source: str, release: Release) -> Release:
    """Download the manifest files for a specific release."""
    log.info(f"Getting Release {source}: {release.name}")
    manifest = release.path
    assembled = SOURCES[source]["assembled"]
    dest = FILEDIR / source / "manifests" / release.name / assembled
    dest.parent.mkdir(exist_ok=True)
    with captured_io(dest):
        kustomize_build([manifest], False)
    return Release(release.name, dest)


def dedupe(this: Release, next: Release) -> Release:
    """Remove duplicate releases.

    returns this release if this==next by content
    returns next release if this!=next by content
    """
    file_next = next.path
    file_this = this.path
    if all((file_this.name == file_next.name, file_this.read_text() != file_next.read_text())):
        # Found different in at least one file
        return next

    next.path.unlink()
    next.path.parent.rmdir()
    log.info(f"Deleting Duplicate Release {next.name}")
    return this


def images(release: Release) -> Generator[str, None, None]:
    """Yield all images from each release."""
    path = release.path
    manifest = FILEDIR / source / "manifests" / release.name / Path(path).name
    with manifest.open() as fp:
        for line in fp:
            m = IMG_RE.match(line)
            if m:
                yield m.groups()[0]


def mirror_image(images: List[str], registry: Registry):
    """Synchronize all source images to target registry, only pushing changed layers."""
    sync_config = SyncConfig(
        version=1,
        creds=[registry.creds],
        sync=[sync_asset(image, registry) for image in images],
    )
    with NamedTemporaryFile(mode="w") as tmpfile:
        yaml.safe_dump(sync_config, tmpfile)
        proc = subprocess.Popen(
            ["./regsync", "once", "-c", tmpfile.name, "-v", "debug"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            encoding="utf-8",
        )
        while proc.returncode is None:
            for line in proc.stdout:
                print(line.strip())
            proc.poll()


def get_argparser():
    """Build the argparse instance."""
    parser = argparse.ArgumentParser(
        description="Update from upstream releases.",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        "--registry",
        default=None,
        type=str,
        nargs=4,
        help="Registry to which images should be mirrored.\n\n"
        "example\n"
        "  --registry my.registry:5000 path username password-file\n"
        "\n"
        "Mirroring depends on binary regsync "
        "(https://github.com/regclient/regclient/releases)\n"
        "and that it is available in the current working directory",
    )
    parser.add_argument(
        "--sources",
        nargs="+",
        default=list(SOURCES.keys()),
        choices=SOURCES.keys(),
        type=str,
        help="Which manifest sources to be updated.\n\n"
        "example\n"
        "  --source storage_provider\n"
        "\n",
    )
    return parser


class UpdateError(Exception):
    """Represents an error performing the update."""


if __name__ == "__main__":
    try:
        args = get_argparser().parse_args()
        registry = Registry(*args.registry) if args.registry else None
        image_set = set()
        for source in args.sources:
            version, source_images = main(source, registry)
            Path(FILEDIR, source, "version").write_text(f"{version}\n")
            print(f"source: {source} latest={version}")
            image_set |= source_images
        print("images:")
        for image in sorted(image_set):
            print(image)
    except UpdateError as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)
