from setuptools import setup, find_packages
from os import path


setup(
    name="pyplet",
    author="Maxime Istasse",
    author_email="istassem@gmail.com",
    url="https://github.com/ispgroupucl/pyplet",
    license='LGPL',
    version="0.1.1",
    python_requires='>=3.6',
    description="A library for creating small web applications with Python alone",
    long_description_content_type="text/markdown",
    packages=find_packages(include=("pyplet",)),
    install_requires=["tornado", "matplotlib"],
)

