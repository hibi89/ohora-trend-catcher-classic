"""Run the RAW suite with outbound socket connections blocked."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch


def no_network(*args, **kwargs):
    raise AssertionError('Network access is forbidden in offline tests')


if __name__ == '__main__':
    suite = unittest.defaultTestLoader.discover(str(Path(__file__).parent), pattern='test_*.py')
    with patch('socket.socket.connect', no_network), \
         patch('socket.socket.connect_ex', no_network), \
         patch('socket.create_connection', no_network):
        result = unittest.TextTestRunner(verbosity=2).run(suite)
    sys.exit(not result.wasSuccessful())
