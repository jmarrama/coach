#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Sync FIT files from a Garmin MTP device. Requires libmtp (brew install libmtp)."""
import ctypes as C
import ctypes.util
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile

DEST = Path(__file__).resolve().parent / 'activities'
MANIFEST = Path(__file__).resolve().parent / '.garmin-sync.json'
ARCHIVE = Path(__file__).resolve().parent / 'coaching/raw'


def archive_fit(path):
    """Preserve an immutable content version before a rolling file is replaced."""
    ARCHIVE.mkdir(parents=True, exist_ok=True)
    raw = path.read_bytes()
    target = ARCHIVE / (hashlib.sha256(raw).hexdigest() + '.fit')
    if not target.exists():
        fd, temp = tempfile.mkstemp(prefix='.archive-', dir=ARCHIVE)
        try:
            with os.fdopen(fd, 'wb') as f:
                f.write(raw)
            os.replace(temp, target)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)

class Entry(C.Structure):
    _fields_ = [('vendor', C.c_char_p), ('vendor_id', C.c_uint16), ('product', C.c_char_p), ('product_id', C.c_uint16), ('flags', C.c_uint32)]
class Raw(C.Structure):
    _fields_ = [('entry', Entry), ('bus', C.c_uint32), ('device', C.c_uint8)]
class File(C.Structure):
    pass
FilePtr = C.POINTER(File)
File._fields_ = [('id', C.c_uint32), ('parent', C.c_uint32), ('storage', C.c_uint32), ('name', C.c_char_p), ('size', C.c_uint64), ('modified', C.c_long), ('type', C.c_int), ('next', FilePtr)]
class Folder(C.Structure):
    pass
FolderPtr = C.POINTER(Folder)
Folder._fields_ = [('id', C.c_uint32), ('parent', C.c_uint32), ('storage', C.c_uint32), ('name', C.c_char_p), ('sibling', FolderPtr), ('child', FolderPtr)]


def library():
    name = ctypes.util.find_library('mtp')
    if not name:
        name = next((str(p) for p in (Path('/opt/homebrew/lib/libmtp.dylib'), Path('/usr/local/lib/libmtp.dylib')) if p.exists()), None)
    if not name:
        raise RuntimeError('libmtp not found; install it with: brew install libmtp')
    lib = C.CDLL(name)
    signatures = {
        'LIBMTP_Init': (None, []),
        'LIBMTP_Detect_Raw_Devices': (C.c_int, [C.POINTER(C.POINTER(Raw)), C.POINTER(C.c_int)]),
        'LIBMTP_Open_Raw_Device': (C.c_void_p, [C.POINTER(Raw)]),
        'LIBMTP_Release_Device': (None, [C.c_void_p]),
        'LIBMTP_Get_Serialnumber': (C.c_void_p, [C.c_void_p]),
        'LIBMTP_FreeMemory': (None, [C.c_void_p]),
        'LIBMTP_Get_Folder_List': (FolderPtr, [C.c_void_p]),
        'LIBMTP_destroy_folder_t': (None, [FolderPtr]),
        'LIBMTP_Get_Filelisting_With_Callback': (FilePtr, [C.c_void_p, C.c_void_p, C.c_void_p]),
        'LIBMTP_destroy_file_t': (None, [FilePtr]),
        'LIBMTP_Get_File_To_File': (C.c_int, [C.c_void_p, C.c_uint32, C.c_char_p, C.c_void_p, C.c_void_p]),
        'LIBMTP_Get_Errorstack': (C.c_void_p, [C.c_void_p]),
        'LIBMTP_Dump_Errorstack': (None, [C.c_void_p]),
        'LIBMTP_Clear_Errorstack': (None, [C.c_void_p]),
    }
    for name, (result, args) in signatures.items():
        fn = getattr(lib, name)
        fn.restype, fn.argtypes = result, args
    lib.LIBMTP_Init()
    return lib


def sha256(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def component(value):
    name = os.fsdecode(value or b'')
    if not name or name in ('.', '..') or '/' in name or '\\' in name:
        raise RuntimeError(f'Unsafe device filename: {name!r}')
    return name


def save_manifest(data):
    fd, name = tempfile.mkstemp(prefix='.garmin-sync-', dir=MANIFEST.parent)
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(data, f, indent=2, sort_keys=True)
            f.write('\n')
        os.replace(name, MANIFEST)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def sync():
    lib = library()
    raw = C.POINTER(Raw)()
    count = C.c_int()
    status = lib.LIBMTP_Detect_Raw_Devices(C.byref(raw), C.byref(count))
    if status != 0:
        raise RuntimeError(f'MTP device detection failed (code {status}); reconnect the watch in MTP mode')
    device = None
    try:
        matches = [i for i in range(count.value) if raw[i].entry.vendor_id == 0x091e]
        if len(matches) != 1:
            raise RuntimeError(f'Expected one Garmin MTP device, found {len(matches)}')
        device = lib.LIBMTP_Open_Raw_Device(C.byref(raw[matches[0]]))
        if not device:
            raise RuntimeError('Could not open Garmin MTP device; close other MTP apps and reconnect')
        serial_ptr = lib.LIBMTP_Get_Serialnumber(device)
        if not serial_ptr:
            raise RuntimeError('The watch did not provide a serial number')
        serial = C.string_at(serial_ptr).decode('utf-8')
        lib.LIBMTP_FreeMemory(serial_ptr)
        folders = lib.LIBMTP_Get_Folder_List(device)
        if not folders:
            lib.LIBMTP_Dump_Errorstack(device)
            raise RuntimeError('Could not list watch folders')
        paths = {}
        def walk(node, parent):
            while node:
                item = node.contents
                path = parent / component(item.name)
                paths[(item.storage, item.id)] = path
                walk(item.child, path)
                node = item.sibling
        try:
            walk(folders, Path())
        finally:
            lib.LIBMTP_destroy_folder_t(folders)
        lib.LIBMTP_Clear_Errorstack(device)
        files = lib.LIBMTP_Get_Filelisting_With_Callback(device, None, None)
        if not files:
            lib.LIBMTP_Dump_Errorstack(device)
            raise RuntimeError('Could not list watch files')
        objects = []
        while files:
            item = files.contents
            next_file = C.cast(C.cast(item.next, C.c_void_p).value, FilePtr)
            name = component(item.name)
            if name.lower().endswith('.fit'):
                parent = paths.get((item.storage, item.parent))
                if parent is None and item.parent not in (0, 0xffffffff):
                    raise RuntimeError(f'Missing parent folder for {name}')
                objects.append((item.id, item.storage, (parent or Path()) / name, item.size, item.modified))
            lib.LIBMTP_destroy_file_t(files)
            files = next_file
        if lib.LIBMTP_Get_Errorstack(device):
            lib.LIBMTP_Dump_Errorstack(device)
            raise RuntimeError('Watch file listing was incomplete')
        manifest = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {}
        if not isinstance(manifest, dict):
            raise ValueError('Invalid sync manifest')
        DEST.mkdir(exist_ok=True)
        copied = skipped = 0
        seen = set()
        print(f'Found {len(objects)} FIT files on Garmin; syncing to {DEST}', flush=True)
        for item_id, storage, path, size, modified in objects:
            relative = Path(f'{storage:08x}') / path
            if relative in seen:
                raise RuntimeError(f'Duplicate device path: {relative}')
            seen.add(relative)
            target = DEST / relative
            key = serial + ':' + relative.as_posix()
            old = manifest.get(key, {})
            if (modified and old.get('size') == size and old.get('modified') == modified
                    and target.is_file() and target.stat().st_size == size
                    and old.get('sha256') == sha256(target)):
                skipped += 1
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            fd, temp = tempfile.mkstemp(prefix='.garmin-', dir=target.parent)
            os.close(fd)
            try:
                lib.LIBMTP_Clear_Errorstack(device)
                if lib.LIBMTP_Get_File_To_File(device, item_id, os.fsencode(temp), None, None) != 0:
                    lib.LIBMTP_Dump_Errorstack(device)
                    raise RuntimeError(f'Failed to download {relative}')
                downloaded = Path(temp)
                if downloaded.stat().st_size != size:
                    raise RuntimeError(f'Incomplete download of {relative}')
                checksum = sha256(downloaded)
                if target.is_file() and sha256(target) == checksum:
                    skipped += 1
                else:
                    if target.is_file():
                        archive_fit(target)
                    archive_fit(downloaded)
                    os.replace(temp, target)
                    copied += 1
                    print(f'Copied {relative}', flush=True)
                manifest[key] = {'size': size, 'modified': modified, 'sha256': checksum}
                save_manifest(manifest)
            finally:
                if os.path.exists(temp):
                    os.unlink(temp)
        print(f'Done: {copied} copied, {skipped} unchanged.', flush=True)
    finally:
        if device:
            lib.LIBMTP_Release_Device(device)
        if raw:
            lib.LIBMTP_FreeMemory(raw)


if __name__ == '__main__':
    try:
        sync()
    except (OSError, ValueError, RuntimeError) as error:
        print(f'Sync failed: {error}', file=sys.stderr)
        sys.exit(1)
