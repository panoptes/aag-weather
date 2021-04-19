#!/usr/bin/env python
# Licensed under an MIT style license - see LICENSE.txt

from setuptools import find_namespace_packages, setup
from configparser import ConfigParser
from distutils.command.build_py import build_py

from aag.version import __version__

# Get some values from the setup.cfg
conf = ConfigParser()
conf.read(['setup.cfg'])
metadata = dict(conf.items('metadata'))

AUTHOR = metadata.get('author', '')
AUTHOR_EMAIL = metadata.get('author_email', '')
DESCRIPTION = metadata.get('description', '')
KEYWORDS = metadata.get('keywords', 'Lunatico AAG weather station')
LICENSE = metadata.get('license', 'unknown')
LONG_DESCRIPTION = metadata.get('long_description', '')
NAME = metadata.get('name', 'aag-weather')
PACKAGENAME = metadata.get('package_name', 'packagename')
URL = metadata.get('url', 'https://projectpanoptes.org')

modules = {
    'required': [
        'astroplan',
        'astropy',
        'Flask',
        'matplotlib',
        'numpy',
        'pandas',
        'panoptes-utils',
        'python-dateutil',
        'python-dotenv',
        'sqlalchemy',
    ],
    'testing': [
        'pycodestyle',
        'pytest',
        'pytest-cov',
    ],
}

setup(name=PACKAGENAME,
      version=__version__,
      description=DESCRIPTION,
      long_description=LONG_DESCRIPTION,
      author=AUTHOR,
      author_email=AUTHOR_EMAIL,
      license=LICENSE,
      url=URL,
      keywords=KEYWORDS,
      python_requires='>=3.8',
      setup_requires=['pytest-runner'],
      install_requires=modules['required'],
      tests_require=modules['testing'],
      packages=find_namespace_packages(exclude=['tests', 'test_*']),
      classifiers=[
          'Development Status :: 3 - Alpha',
          'Environment :: Console',
          'Intended Audience :: Science/Research',
          'License :: OSI Approved :: MIT License',
          'Operating System :: POSIX',
          'Programming Language :: C',
          'Programming Language :: Python :: 3',
          'Programming Language :: Python :: 3.8',
          'Programming Language :: Python :: 3 :: Only',
          'Topic :: Scientific/Engineering :: Astronomy',
          'Topic :: Scientific/Engineering :: Physics',
      ],
      cmdclass={'build_py': build_py}
      )
