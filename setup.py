import os
from setuptools import setup, find_packages

this_directory = os.path.abspath(os.path.dirname(__file__))

BASE_DEPS = [
    'python-dotenv',
    'requests',
    'ollama',
    "jebin_lib @ git+https://github.com/jebin2/lib.git",
    "custom_logger @ git+https://github.com/jebin2/custom_logger.git",
]

extras_require = {
    'all': [],
}

all_deps = []

setup(
    name="ttt-runner",
    version="1.0.0",
    author="Jebin Einstein",
    author_email="jebineinstein@gmail.com",
    description="A flexible text-to-text generation runner (Qwen/Qwen3.5-4B)",
    url="https://github.com/jebin2/TTT",

    packages=find_packages(),

    install_requires=BASE_DEPS,
    extras_require=extras_require,

    entry_points={
        'console_scripts': [
            'ttt-generate=ttt.runner:main',
        ],
    },

    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Topic :: Scientific/Engineering :: Artificial Intelligence",
    ],
    python_requires='>=3.10',
)
