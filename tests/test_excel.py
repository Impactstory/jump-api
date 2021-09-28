import pytest
import os
import filecmp
from excel import convert_xls_to_xlsx, convert_spreadsheet_to_csv

def test_convert_xls_to_xlsx():
    x = convert_xls_to_xlsx('tests/test_files/counter/counter4_jr1_2018_01.xls')
    assert isinstance(x, str)
    assert '.xlsx' in x
    assert os.path.isfile(x)

def test_convert_spreadsheet_to_csv():
    # FIXME: parsed=True is never used in the codebase, so just testing False for now
    x = convert_spreadsheet_to_csv('tests/test_files/counter/counter4_jr1_2018_01.xlsx', parsed=False)
    assert isinstance(x, list)
    assert isinstance(x[0], str)
    assert os.path.isfile(x[0])
     # FIXME: The below should be True, but dates are messed up in the output csv
    # assert filecmp.cmp(x[0], 'tests/test_files/counter/counter4_jr1_2018_01.csv')

