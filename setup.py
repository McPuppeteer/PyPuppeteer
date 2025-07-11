from setuptools import setup

with open("README.md", "r", encoding='utf-8') as file:
  long_description = file.read()


setup(
  name             = 'McPuppeteer',
  version          =  "0.0.3",
  description      = 'A python library for fully controlling the player in Minecraft',
  author           = 'PsychedelicPalimpsest',
  url              = 'https://github.com/PsychedelicPalimpsest/PyMcPuppeteer',
  license          = "GPLv3",
  long_description = long_description,
  install_requires = ["nbtlib==1.12.1"],
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
