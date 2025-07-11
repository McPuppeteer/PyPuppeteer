from setuptools import setup
import os
DIR = os.path.dirname(os.path.abspath(__file__))


with open(os.path.join(DIR, "README.md"), "r", encoding='utf-8') as file:
  long_description = file.read()
with open(os.path.join(DIR, "requirements.txt"), "r", encoding='utf-8') as file:
  deps = [l.strip() for l in file.read().split("\n")]




setup(
  name             = 'McPuppeteer',
  version          =  "0.0.3",
  description      = 'A python library for fully controlling the player in Minecraft',
  author           = 'PsychedelicPalimpsest',
  url              = 'https://github.com/PsychedelicPalimpsest/PyMcPuppeteer',
  license          = "GPLv3",
  long_description = long_description,
  install_requires = deps,
  long_description_content_type="text/markdown",
  packages         = ['puppet'],
  classifiers      = [
        "Intended Audience :: Developers",
        "License :: OSI Approved :: GNU General Public License v3 (GPLv3)",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Topic :: Games/Entertainment",
        "Topic :: Software Development :: Libraries :: Python Modules"
  ]
)
