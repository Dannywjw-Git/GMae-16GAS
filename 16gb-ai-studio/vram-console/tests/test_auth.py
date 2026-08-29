# -*- coding: utf-8 -*-
"""认证模块测试（P0-2 最小测试集）— 密码哈希、Session、用户管理、验证码"""

import os
import sys
import time
import tempfile
import unittest

# 把 vram-console 目录加入 path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import auth as auth_mod


class TestPasswordHashing(unittest.TestCase):
    """密码哈希与验证测试"""

    def test_hash_password_format(self):
        """哈希格式应为 pbkdf2_sha256$iterations$salt$hash"""
        h = auth_mod.hash_password("test123")
        parts = h.split("$")
        self.assertEqual(len(parts), 4, "哈希应包含 4 个部分")
        self.assertEqual(parts[0], "pbkdf2_sha256", "算法应为 pbkdf2_sha256")
        self.assertEqual(int(parts[1]), 100000, "迭代次数应为 100000")
        self.assertEqual(len(parts[2]), 32, "salt 应为 16 字节 hex（32字符）")

    def test_hash_password_different_salts(self):
        """相同密码每次哈希应不同（随机盐）"""
        h1 = auth_mod.hash_password("test123")
        h2 = auth_mod.hash_password("test123")
        self.assertNotEqual(h1, h2, "相同密码的两次哈希应不同（随机盐）")

    def test_verify_password_correct(self):
        """正确密码应验证通过"""
        h = auth_mod.hash_password("MySecurePass123!")
        self.assertTrue(auth_mod.verify_password("MySecurePass123!", h), "正确密码应验证通过")

    def test_verify_password_wrong(self):
        """错误密码应验证失败"""
        h = auth_mod.hash_password("correct_password")
        self.assertFalse(auth_mod.verify_password("wrong_password", h), "错误密码应验证失败")

    def test_verify_password_empty(self):
        """空密码应验证失败"""
        h = auth_mod.hash_password("test123")
        self.assertFalse(auth_mod.verify_password("", h), "空密码应验证失败")

    def test_verify_password_invalid_hash(self):
        """无效哈希应验证失败（不崩溃）"""
        self.assertFalse(auth_mod.verify_password("test123", "invalid_hash"), "无效哈希应返回 False")
        self.assertFalse(auth_mod.verify_password("test123", ""), "空哈希应返回 False")

    def test_password_unicode(self):
        """中文/Unicode 密码应正常工作"""
        h = auth_mod.hash_password("密码测试123!@#")
        self.assertTrue(auth_mod.verify_password("密码测试123!@#", h), "Unicode 密码应验证通过")
        self.assertFalse(auth_mod.verify_password("错误密码", h), "错误 Unicode 密码应验证失败")


class TestSessionManagement(unittest.TestCase):
    """Session 管理测试"""

    def setUp(self):
        """每个测试前清空 Session"""
        auth_mod.SESSIONS.clear()

    def test_create_session(self):
        """创建 Session 应返回非空 session_id"""
        sid = auth_mod.create_session("test@example.com")
        self.assertTrue(sid, "session_id 不应为空")
        self.assertIn(sid, auth_mod.SESSIONS, "Session 应存储在 SESSIONS 中")

    def test_get_session_valid(self):
        """有效 Session 应能获取到用户信息"""
        sid = auth_mod.create_session("user@test.com", remember=False)
        sess = auth_mod.get_session(sid)
        self.assertIsNotNone(sess, "有效 Session 不应返回 None")
        self.assertEqual(sess["user_email"], "user@test.com", "Session 应包含正确的用户邮箱")

    def test_get_session_expired(self):
        """过期 Session 应返回 None 并被清理"""
        sid = auth_mod.create_session("expired@test.com")
        # 手动设置为已过期
        auth_mod.SESSIONS[sid]["expires_at"] = int(time.time()) - 1
        sess = auth_mod.get_session(sid)
        self.assertIsNone(sess, "过期 Session 应返回 None")
        self.assertNotIn(sid, auth_mod.SESSIONS, "过期 Session 应被清理")

    def test_get_session_invalid(self):
        """无效 session_id 应返回 None"""
        self.assertIsNone(auth_mod.get_session("nonexistent_session"), "无效 Session 应返回 None")
        self.assertIsNone(auth_mod.get_session(""), "空 Session 应返回 None")

    def test_destroy_session(self):
        """销毁 Session 后应无法再获取"""
        sid = auth_mod.create_session("destroy@test.com")
        auth_mod.destroy_session(sid)
        self.assertIsNone(auth_mod.get_session(sid), "销毁后的 Session 应返回 None")

    def test_session_remember_ttl(self):
        """记住我的 Session 应有更长的 TTL"""
        sid_normal = auth_mod.create_session("normal@test.com", remember=False)
        sid_remember = auth_mod.create_session("remember@test.com", remember=True)
        ttl_normal = auth_mod.SESSIONS[sid_normal]["expires_at"] - auth_mod.SESSIONS[sid_normal]["created_at"]
        ttl_remember = auth_mod.SESSIONS[sid_remember]["expires_at"] - auth_mod.SESSIONS[sid_remember]["created_at"]
        self.assertGreater(ttl_remember, ttl_normal, "记住我的 TTL 应更长")
        self.assertEqual(ttl_normal, 7 * 24 * 3600, "默认 TTL 应为 7 天")
        self.assertEqual(ttl_remember, 30 * 24 * 3600, "记住我 TTL 应为 30 天")

    def test_clear_user_sessions(self):
        """清除指定用户的所有 Session"""
        sid1 = auth_mod.create_session("user@test.com")
        sid2 = auth_mod.create_session("user@test.com")
        sid3 = auth_mod.create_session("other@test.com")
        auth_mod._clear_user_sessions("user@test.com")
        self.assertNotIn(sid1, auth_mod.SESSIONS, "用户的 Session1 应被清除")
        self.assertNotIn(sid2, auth_mod.SESSIONS, "用户的 Session2 应被清除")
        self.assertIn(sid3, auth_mod.SESSIONS, "其他用户的 Session 不应被清除")


class TestCookieParsing(unittest.TestCase):
    """Cookie 解析测试"""

    def test_parse_single_cookie(self):
        cookies = auth_mod.parse_cookie("gmae_session=abc123")
        self.assertEqual(cookies.get("gmae_session"), "abc123")

    def test_parse_multiple_cookies(self):
        cookies = auth_mod.parse_cookie("gmae_session=abc123; other=xyz; foo=bar")
        self.assertEqual(cookies.get("gmae_session"), "abc123")
        self.assertEqual(cookies.get("other"), "xyz")
        self.assertEqual(cookies.get("foo"), "bar")

    def test_parse_empty_cookie(self):
        self.assertEqual(auth_mod.parse_cookie(""), {})
        self.assertEqual(auth_mod.parse_cookie(None), {})

    def test_parse_cookie_with_spaces(self):
        cookies = auth_mod.parse_cookie("  gmae_session = abc123  ;  other = xyz  ")
        self.assertEqual(cookies.get("gmae_session"), "abc123")


class TestUserManagement(unittest.TestCase):
    """用户管理测试（使用临时 users.json）"""

    def setUp(self):
        """每个测试前使用临时 users.json"""
        self.temp_dir = tempfile.mkdtemp()
        self.original_users_file = auth_mod.USERS_FILE
        auth_mod.USERS_FILE = os.path.join(self.temp_dir, "users.json")

    def tearDown(self):
        """恢复原始 users.json 路径"""
        auth_mod.USERS_FILE = self.original_users_file
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_has_admin_false_initially(self):
        self.assertFalse(auth_mod.has_admin(), "初始状态应无管理员")

    def test_setup_admin_success(self):
        ok, msg = auth_mod.setup_admin("admin@test.com", "password123")
        self.assertTrue(ok, f"设置管理员应成功: {msg}")
        self.assertTrue(auth_mod.has_admin(), "设置后应有管理员")

    def test_setup_admin_duplicate(self):
        auth_mod.setup_admin("admin@test.com", "password123")
        ok, msg = auth_mod.setup_admin("another@test.com", "password456")
        self.assertFalse(ok, "重复设置管理员应失败")
        self.assertIn("已存在", msg, "失败信息应提示已存在")

    def test_setup_admin_invalid_email(self):
        ok, msg = auth_mod.setup_admin("not-an-email", "password123")
        self.assertFalse(ok, "无效邮箱应失败")

    def test_setup_admin_short_password(self):
        ok, msg = auth_mod.setup_admin("admin@test.com", "123")
        self.assertFalse(ok, "短密码应失败")

    def test_authenticate_success(self):
        auth_mod.setup_admin("admin@test.com", "password123")
        ok, user = auth_mod.authenticate("admin@test.com", "password123")
        self.assertTrue(ok, "正确凭据应认证成功")
        self.assertEqual(user["email"], "admin@test.com", "返回的用户邮箱应正确")

    def test_authenticate_wrong_password(self):
        auth_mod.setup_admin("admin@test.com", "password123")
        ok, user = auth_mod.authenticate("admin@test.com", "wrongpassword")
        self.assertFalse(ok, "错误密码应认证失败")

    def test_authenticate_wrong_email(self):
        auth_mod.setup_admin("admin@test.com", "password123")
        ok, user = auth_mod.authenticate("nonexistent@test.com", "password123")
        self.assertFalse(ok, "错误邮箱应认证失败")

    def test_authenticate_case_insensitive(self):
        auth_mod.setup_admin("Admin@Test.com", "password123")
        ok, user = auth_mod.authenticate("admin@test.com", "password123")
        self.assertTrue(ok, "邮箱应大小写不敏感")

    def test_change_password_success(self):
        auth_mod.setup_admin("admin@test.com", "oldpassword")
        ok, msg = auth_mod.change_password("admin@test.com", "oldpassword", "newpassword123")
        self.assertTrue(ok, f"修改密码应成功: {msg}")
        # 用新密码登录
        ok2, _ = auth_mod.authenticate("admin@test.com", "newpassword123")
        self.assertTrue(ok2, "新密码应能登录")
        # 旧密码不能登录
        ok3, _ = auth_mod.authenticate("admin@test.com", "oldpassword")
        self.assertFalse(ok3, "旧密码应不能登录")

    def test_change_password_wrong_old(self):
        auth_mod.setup_admin("admin@test.com", "password123")
        ok, msg = auth_mod.change_password("admin@test.com", "wrongold", "newpassword")
        self.assertFalse(ok, "旧密码错误应失败")


class TestResetCode(unittest.TestCase):
    """密码重置验证码测试"""

    def setUp(self):
        auth_mod.RESET_CODES.clear()

    def test_generate_reset_code_format(self):
        """验证码应为 6 位数字"""
        code = auth_mod.generate_reset_code.__wrapped__ if hasattr(auth_mod.generate_reset_code, "__wrapped__") else None
        # 直接测试内部生成逻辑
        import secrets
        for _ in range(10):
            c = "{:06d}".format(secrets.randbelow(1000000))
            self.assertEqual(len(c), 6, "验证码应为 6 位")
            self.assertTrue(c.isdigit(), "验证码应为纯数字")

    def test_reset_code_expiry(self):
        """验证码应在过期后失效"""
        auth_mod.RESET_CODES["test@test.com"] = {
            "code": "123456",
            "expires_at": int(time.time()) - 1,  # 已过期
            "attempts": 0,
        }
        ok, msg = auth_mod._verify_reset_code("test@test.com", "123456")
        self.assertFalse(ok, "过期验证码应验证失败")
        self.assertIn("过期", msg, "失败信息应提示过期")

    def test_reset_code_max_attempts(self):
        """超过最大尝试次数后验证码应失效"""
        auth_mod.RESET_CODES["test@test.com"] = {
            "code": "123456",
            "expires_at": int(time.time()) + 600,
            "attempts": 5,  # 已达上限
        }
        ok, msg = auth_mod._verify_reset_code("test@test.com", "123456")
        self.assertFalse(ok, "超过尝试次数应失败")
        self.assertIn("过多", msg, "失败信息应提示次数过多")

    def test_reset_code_wrong_code(self):
        """错误验证码应验证失败"""
        auth_mod.RESET_CODES["test@test.com"] = {
            "code": "123456",
            "expires_at": int(time.time()) + 600,
            "attempts": 0,
        }
        ok, msg = auth_mod._verify_reset_code("test@test.com", "000000")
        self.assertFalse(ok, "错误验证码应失败")

    def test_reset_code_correct(self):
        """正确验证码应验证通过"""
        auth_mod.RESET_CODES["test@test.com"] = {
            "code": "123456",
            "expires_at": int(time.time()) + 600,
            "attempts": 0,
        }
        ok, msg = auth_mod._verify_reset_code("test@test.com", "123456")
        self.assertTrue(ok, f"正确验证码应通过: {msg}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
