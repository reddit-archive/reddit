# The contents of this file are subject to the Common Public Attribution
# License Version 1.0. (the "License"); you may not use this file except in
# compliance with the License. You may obtain a copy of the License at
# http://code.reddit.com/LICENSE. The License is based on the Mozilla Public
# License Version 1.1, but Sections 14 and 15 have been added to cover use of
# software over a computer network and provide for limited attribution for the
# Original Developer. In addition, Exhibit A has been modified to be consistent
# with Exhibit B.
#
# Software distributed under the License is distributed on an "AS IS" basis,
# WITHOUT WARRANTY OF ANY KIND, either express or implied. See the License for
# the specific language governing rights and limitations under the License.
#
# The Original Code is reddit.
#
# The Original Developer is the Initial Developer.  The Initial Developer of
# the Original Code is reddit Inc.
#
# All portions of the code written by reddit are Copyright (c) 2006-2012 reddit
# Inc. All Rights Reserved.
###############################################################################

import unittest

from r2.lib import tracking


KEY_SIZE = tracking.KEY_SIZE
MESSAGE = "the quick brown fox jumped over..."
BLOCK_O_PADDING = ("\x10\x10\x10\x10\x10\x10\x10\x10"
                   "\x10\x10\x10\x10\x10\x10\x10\x10")


class TestPadding(unittest.TestCase):
    def test_pad_empty_string(self):
        padded = tracking._pad_message("")
        self.assertEquals(padded, BLOCK_O_PADDING)

    def test_pad_round_string(self):
        padded = tracking._pad_message("x" * KEY_SIZE)
        self.assertEquals(len(padded), KEY_SIZE * 2)
        self.assertEquals(padded[KEY_SIZE:], BLOCK_O_PADDING)

    def test_unpad_empty_message(self):
        unpadded = tracking._unpad_message("")
        self.assertEquals(unpadded, "")

    def test_unpad_evil_message(self):
        evil = ("a" * 88) + chr(57)
        result = tracking._unpad_message(evil)
        self.assertEquals(result, "")

    def test_padding_roundtrip(self):
        tested = tracking._unpad_message(tracking._pad_message(MESSAGE))
        self.assertEquals(MESSAGE, tested)


class TestEncryption(unittest.TestCase):
    def test_encryption_roundtrip(self):
        tested = tracking.decrypt(tracking.encrypt(MESSAGE))
        self.assertEquals(MESSAGE, tested)


if __name__ == '__main__':
    unittest.main()
