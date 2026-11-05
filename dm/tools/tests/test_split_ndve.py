"""NDSR packs are lists of 8-byte items (ndsr_shaders). Synthetic bytes only; NDVE files are dm/gfx/tests/test_ndve.py's."""
import struct
import unittest

from dm.tools.tests.test_split_gzip import ss


def nvn2(seed, code_len=0x100, ctl_len=0xe0):
    """An NVN2 compute shader: a control section (magic, version 0xc9, the code length at +0x44, stage byte 5 at +0x56) and its code area"""
    ctl = bytearray(ctl_len); struct.pack_into('<II', ctl, 0, 0x98761234, 0xc9); struct.pack_into('<I', ctl, 0x44, code_len); ctl[0x56] = 5
    struct.pack_into('<3I', ctl, 0x58, 8, 8, 1); ctl[0x60] = seed
    code = bytes([seed]) * code_len
    return bytes(ctl), code


def item(off, length, kind): return struct.pack('<II', off, length << 4 | kind)


def ndsr(shaders, data_between):
    """An NDSR pack of the newer header (+4 0x40100, items from +0x14): one data item first, then per shader a control item and a code item, with data_between data items after each"""
    head = bytearray(b'NDSR' + struct.pack('<4I', 0x40100, 0, 0, 0))
    n_items = 1 + len(shaders) * (2 + data_between) + 1
    body = bytearray(bytes(0x14 + 8 * n_items - len(head)))
    blob = head + body
    blob += bytes(-len(blob) % 0x100)
    items = [item(len(blob), 4, 0xb)]; blob += bytes(4)
    for ctl, code in shaders:
        blob += bytes(-len(blob) % 0x100); c = len(blob); blob += ctl
        blob += bytes(-len(blob) % 0x100); k = len(blob); blob += code
        items += [item(c, len(ctl), 6), item(k, len(code), 7)]
        for _ in range(data_between): items.append(item(len(blob), 4, 9)); blob += bytes(4)
    struct.pack_into(f'{len(items) * 8}s', blob, 0x14, b''.join(items))   # a zero item ends the list
    return bytes(blob)


class NdsrItems(unittest.TestCase):
    def test_odd_data_items_keep_every_shader(self):
        # one data item between the two shaders shifts the second off a 16-byte record grid; the item walk still pairs each control item with the code item after it
        shaders = [nvn2(1), nvn2(2, 0x200)]
        found = ss.ndsr_shaders(ndsr(shaders, 1), 'p')
        self.assertEqual([(st, ctl, code) for _, st, ctl, code in found], [('cs', *s) for s in shaders])

    def test_paired_records_unchanged(self):
        shaders = [nvn2(1), nvn2(2), nvn2(3)]
        found = ss.ndsr_shaders(ndsr(shaders, 0), 'p')
        self.assertEqual([code for *_, code in found], [s[1] for s in shaders])


if __name__ == '__main__':
    unittest.main()
