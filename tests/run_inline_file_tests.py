# (c) 2015-2016 Acellera Ltd http://www.acellera.com
# All Rights Reserved
# Distributed under HTMD Software License Agreement
# No redistribution in whole or part
#
import fnmatch
import os
from subprocess import call, check_output
import sys

excludedfolders = ('./tests', './doc', './htmdlib')
excludedfiles = ('__init__.py', 'license_headers.py', 'setup.py', 'sync_conda_with_omnia.py', 'makerelease.py')   # Trailing comma needed otherwise it's not a tuple


def excluded(name, exclusionlist):
    for e in exclusionlist:
        if name.startswith(e):
            return True
    return False

# Collecting py files to run
filestotest = []
for root, dirnames, filenames in os.walk('.'):
    if excluded(root, excludedfolders):
        continue

    for filename in fnmatch.filter(filenames, '*.py'):
        if not excluded(filename, excludedfiles):
            filestotest.append(os.path.join(root, filename))

# Running py files
failed = []

for f in filestotest:
    print(' ************************  Running "{}"  ************************'.format(f))
    if f.endswith('amber.py') or f.endswith('charmm.py'):
        out = call('export PYTHONHASHSEED=1; python {}'.format(f), shell=True)
    else:
        out = call('python {}'.format(f), shell=True)
    print(' ************************  Result : {}  ************************'.format(out))
    if out != 0:
        failed.append(f)

# Reporting errors
if len(failed) != 0:
    errormsg = 'Tests failed for the following files:\n'
    for f in failed:
        errormsg += '{}\n'.format(f)
    raise AssertionError(errormsg)

print(' All tests passed! ')



