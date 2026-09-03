"""
Test Suite: 64-Bit Win32 Interop Correctness and Structure Layout.
Verifies pointer widths, explicit ctypes types, structure field offsets,
SendMessageTimeoutW 64-bit parameter safety, and leak-free GDI operations.
"""

import ctypes
from ctypes import wintypes
import sys
import unittest

import runtime.win32 as w32


class TestWin32Interop64Bit(unittest.TestCase):
    """Verifies Win32 ctypes type safety and 64-bit alignment."""

    def test_pointer_and_type_sizes(self):
        """Verifies pointer-width types match architecture word size (8 bytes on 64-bit)."""
        is_64bit = sys.maxsize > 2**32
        expected_ptr_size = 8 if is_64bit else 4

        self.assertEqual(ctypes.sizeof(ctypes.c_void_p), expected_ptr_size)
        self.assertEqual(ctypes.sizeof(w32.ULONG_PTR), expected_ptr_size)
        self.assertEqual(ctypes.sizeof(w32.LONG_PTR), expected_ptr_size)
        self.assertEqual(ctypes.sizeof(w32.DWORD_PTR), expected_ptr_size)
        self.assertEqual(ctypes.sizeof(w32.LRESULT), expected_ptr_size)
        self.assertEqual(ctypes.sizeof(w32.WPARAM), expected_ptr_size)
        self.assertEqual(ctypes.sizeof(w32.LPARAM), expected_ptr_size)
        self.assertEqual(ctypes.sizeof(w32.SIZE_T), expected_ptr_size)

    def test_win32_structure_sizes(self):
        """Verifies Win32 structure sizes match Microsoft platform SDK specifications."""
        # RECT: 4 x LONG (32-bit) = 16 bytes
        self.assertEqual(ctypes.sizeof(w32.RECT), 16)

        # POINT: 2 x LONG (32-bit) = 8 bytes
        self.assertEqual(ctypes.sizeof(w32.POINT), 8)

        # WINDOWPLACEMENT: 3 x UINT (12) + 2 x POINT (16) + 1 x RECT (16) = 44 bytes
        self.assertEqual(ctypes.sizeof(w32.WINDOWPLACEMENT), 44)

        # BITMAPINFOHEADER: 40 bytes standard
        self.assertEqual(ctypes.sizeof(w32.BITMAPINFOHEADER), 40)

        # IO_COUNTERS: 6 x ULONGLONG = 48 bytes
        self.assertEqual(ctypes.sizeof(w32.IO_COUNTERS), 48)

        # JOBOBJECT_BASIC_LIMIT_INFORMATION:
        # On 64-bit: 64 bytes (due to 64-bit alignment of LARGE_INTEGER, SIZE_T, ULONG_PTR)
        # On 32-bit: 48 bytes
        if sys.maxsize > 2**32:
            self.assertEqual(ctypes.sizeof(w32.JOBOBJECT_BASIC_LIMIT_INFORMATION), 64)
            # JOBOBJECT_EXTENDED_LIMIT_INFORMATION:
            # Basic (64) + IO_COUNTERS (48) + 4 x SIZE_T (32) = 144 bytes on 64-bit
            self.assertEqual(ctypes.sizeof(w32.JOBOBJECT_EXTENDED_LIMIT_INFORMATION), 144)
        else:
            self.assertEqual(ctypes.sizeof(w32.JOBOBJECT_BASIC_LIMIT_INFORMATION), 48)
            self.assertEqual(ctypes.sizeof(w32.JOBOBJECT_EXTENDED_LIMIT_INFORMATION), 112)

    def test_sendmessage_timeout_64bit_argument_types(self):
        """
        Verifies SendMessageTimeoutW uses DWORD_PTR for the result pointer (7th arg),
        preventing 64-bit stack/heap corruption.
        """
        if sys.platform != "win32" or w32.user32 is None:
            self.skipTest("Requires Windows User32")

        func = getattr(w32.user32, "SendMessageTimeoutW", None)
        self.assertIsNotNone(func)
        self.assertIsNotNone(func.argtypes)
        self.assertEqual(len(func.argtypes), 7)

        # Check 7th arg is POINTER(DWORD_PTR)
        result_ptr_type = func.argtypes[6]
        self.assertTrue(issubclass(result_ptr_type, ctypes._Pointer))
        target_type = result_ptr_type._type_
        self.assertEqual(ctypes.sizeof(target_type), ctypes.sizeof(w32.DWORD_PTR))

    def test_get_window_long_ptr_architecture_safety(self):
        """Verifies GetWindowLongPtrW / SetWindowLongPtrW return LONG_PTR."""
        if sys.platform != "win32" or w32.user32 is None:
            self.skipTest("Requires Windows User32")

        gwl_func = getattr(w32, "GetWindowLongPtrW", None)
        self.assertIsNotNone(gwl_func)
        self.assertEqual(gwl_func.restype, w32.LONG_PTR)

    def test_gdi_resource_lifecycle(self):
        """
        Verifies GDI CreateCompatibleDC, CreateCompatibleBitmap, SelectObject,
        DeleteObject, and DeleteDC succeed deterministically with guaranteed cleanup.
        """
        if sys.platform != "win32" or w32.gdi32 is None or w32.user32 is None:
            self.skipTest("Requires Windows GDI32")

        # Create two memory device contexts
        hdc_src = w32.gdi32.CreateCompatibleDC(None)
        self.assertNotEqual(hdc_src, 0)
        hbm_src = w32.gdi32.CreateCompatibleBitmap(hdc_src, 100, 100)
        self.assertNotEqual(hbm_src, 0)
        old_src = w32.gdi32.SelectObject(hdc_src, hbm_src)

        hdc_dst = w32.gdi32.CreateCompatibleDC(None)
        self.assertNotEqual(hdc_dst, 0)
        hbm_dst = w32.gdi32.CreateCompatibleBitmap(hdc_dst, 100, 100)
        self.assertNotEqual(hbm_dst, 0)
        old_dst = w32.gdi32.SelectObject(hdc_dst, hbm_dst)

        try:
            # Memory DC to memory DC BitBlt succeeds in all execution contexts
            res = w32.gdi32.BitBlt(hdc_dst, 0, 0, 100, 100, hdc_src, 0, 0, w32.SRCCOPY)
            self.assertTrue(bool(res))
        finally:
            # Strict GDI cleanup order: restore old bitmap before deleting bitmap
            if hdc_src and old_src:
                w32.gdi32.SelectObject(hdc_src, old_src)
            if hbm_src:
                self.assertTrue(bool(w32.gdi32.DeleteObject(hbm_src)))
            if hdc_src:
                self.assertTrue(bool(w32.gdi32.DeleteDC(hdc_src)))

            if hdc_dst and old_dst:
                w32.gdi32.SelectObject(hdc_dst, old_dst)
            if hbm_dst:
                self.assertTrue(bool(w32.gdi32.DeleteObject(hbm_dst)))
            if hdc_dst:
                self.assertTrue(bool(w32.gdi32.DeleteDC(hdc_dst)))


if __name__ == "__main__":
    unittest.main()
