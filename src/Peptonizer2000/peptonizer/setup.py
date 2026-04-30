from setuptools import setup, find_packages

setup(
    name="peptonizer",
    version="0.1",
    packages=find_packages(),
    install_requires=[
        "numpy",
        "scipy",
        "networkx",
        "pandas",
        "rbo",
        "matplotlib",
        "requests"
    ],
    author="Tanja Holstein",
    author_email="tanja.holstein@ugent.be",
    description="The Peptonizer allows you to easily find out which taxa are most likely present in a metaproteomics sample of interest.",
    url="https://github.com/compomics/Peptonizer2000",  # Replace with your GitHub URL
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    python_requires='>=3.6',
)
