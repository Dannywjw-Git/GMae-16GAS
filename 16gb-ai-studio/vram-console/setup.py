#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GMae CLI 安装配置
安装方式：pip install -e .
安装后可直接使用 `gmae` 命令。
"""
from setuptools import setup, find_packages

setup(
    name="gmae-cli",
    version="1.0.0",
    description="GMae 显存指挥家 - 命令行工具（One GPU, Infinite Models）",
    long_description=open("README_CLI.md", encoding="utf-8").read() if __import__("os").path.exists("README_CLI.md") else "",
    long_description_content_type="text/markdown",
    author="GMae Team",
    license="MIT",
    packages=find_packages(include=["cli", "cli.*"]),
    python_requires=">=3.8",
    install_requires=[],  # 零第三方依赖，仅用标准库
    entry_points={
        "console_scripts": [
            "gmae=cli.main:main",
        ],
    },
    classifiers=[
        "Development Status :: 4 - Beta",
        "Environment :: Console",
        "Intended Audience :: Developers",
        "Intended Audience :: System Administrators",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Topic :: System :: Monitoring",
        "Topic :: System :: Systems Administration",
    ],
    keywords="gpu vram scheduler cli ai-studio",
)
