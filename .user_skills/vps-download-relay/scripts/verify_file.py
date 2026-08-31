#!/usr/bin/env python3
"""
验证下载文件的完整性。
支持: .whl/.zip/.jar (zip), .tar/.tar.gz (tar), 其他 (大小检查)

用法: python verify_file.py <filepath>
"""
import sys
import os
import zipfile
import tarfile

def verify_zip(filepath):
    """验证 zip/whl/jar 文件"""
    try:
        with zipfile.ZipFile(filepath) as z:
            bad = z.testzip()
            if bad:
                print(f"❌ CORRUPT at: {bad}")
                return False
            print(f"✅ ZIP OK, {len(z.namelist())} files")
            return True
    except Exception as e:
        print(f"❌ ERROR: {e}")
        return False

def verify_tar(filepath):
    """验证 tar/tar.gz 文件"""
    try:
        with tarfile.open(filepath) as t:
            members = t.getmembers()
            print(f"✅ TAR OK, {len(members)} entries")
            return True
    except Exception as e:
        print(f"❌ ERROR: {e}")
        return False

def verify_size(filepath, expected_size=None):
    """仅检查文件大小（作为辅助验证）"""
    size = os.path.getsize(filepath)
    print(f"📦 File size: {size / 1024 / 1024:.1f} MB")
    if expected_size:
        if abs(size - expected_size) < 1024:  # 1KB 容差
            print(f"✅ Size matches expected {expected_size} bytes")
            return True
        else:
            print(f"⚠️  Size mismatch: expected {expected_size}, got {size}")
            return False
    return True  # 无期望值时仅报告

def main():
    if len(sys.argv) < 2:
        print("用法: python verify_file.py <filepath> [expected_size_bytes]")
        sys.exit(1)
    
    filepath = sys.argv[1]
    expected_size = int(sys.argv[2]) if len(sys.argv) > 2 else None
    
    if not os.path.exists(filepath):
        print(f"❌ File not found: {filepath}")
        sys.exit(1)
    
    ext = os.path.splitext(filepath)[1].lower()
    
    if ext in ['.whl', '.zip', '.jar', '.egg']:
        ok = verify_zip(filepath)
    elif ext in ['.tar', '.gz', '.tgz', '.bz2']:
        ok = verify_tar(filepath)
    else:
        print(f"ℹ️  Unknown type '{ext}', size check only")
        ok = verify_size(filepath, expected_size)
    
    sys.exit(0 if ok else 1)

if __name__ == "__main__":
    main()
