from setuptools import setup, find_packages

setup(
    name="aiida_custom_schedulers",
    version="0.1.0",
    packages=find_packages(),
    entry_points={
        "aiida.schedulers": [
            "pbspro_no_select = aiida_custom_schedulers.custom_pbspro:NoSelectPbsproScheduler",
        ],
    },
)