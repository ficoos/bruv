#!/usr/bin/env python

from setuptools import setup

setup(name='bruv',
      version='0.1',
      description='Better Review Ultimate Viewer',
      author='Saggi Mizrahi',
      packages=['bruv'],
      url='https://github.com/ficoos/bruv',
      package_data={
        'html': ['html/*.html'],
        'js': ['js/*.js'],
        'css': ['css/*.css'],
        'images': ['images/*.png'],
      },
      install_requires=[
        'paramiko',
        'bottle',
        'gerrit',
      ],
      dependency_links = [
        'git+https://github.com/ficoos/python-gerrit.git#egg=gerrit'
      ],
      entry_points = {
          'console_scripts': [
              'bruv = bruv.bruv',
              'webruvd = bruv.webruvd:main',
          ]
      }
)

