# -*- coding: utf-8 -*-
"""TLS / HTTPS 支持（呼应反馈 202608090002：禁用 http、使用 https、可配置）。

设计要点：
- 默认不启用（enabled=False），保持向后兼容，已有部署行为不变。
- 启用后优先使用用户提供的 cert_file / key_file；
  若未提供或文件不存在，则自动生成自签名证书一次（默认 10 年，CN=localhost，
  SAN 含 localhost 与 127.0.0.1），用户随后可替换为受信任证书。
- 全部由配置文件（web_config.json 的 tls 段）控制，用户可自行开关与替换证书。
- 任何证书加载失败都安全回退到明文 HTTP，避免服务起不来。
"""
import os
import ssl
import datetime
import ipaddress


def _get_logger():
    from liblog import get_service_logger
    return get_service_logger('dbox-web')


def _resolve_path(p, config_dir):
    """将配置中的证书路径解析为绝对路径。

    - 绝对且存在：直接返回；
    - 相对路径：视为相对用户配置目录；
    - 绝对但尚不存在（用户指定的待放置路径）：返回该绝对路径。
    """
    if not p:
        return None
    if os.path.isabs(p) and os.path.exists(p):
        return p
    if os.path.isabs(p):
        return p
    return os.path.join(config_dir, p)


def _generate_self_signed(cert_path, key_path, common_name='localhost'):
    """生成一份自签名证书与私钥（PEM），返回 (cert_path, key_path)。"""
    from cryptography import x509
    from cryptography.x509.oid import NameOID
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])
    now = datetime.datetime.utcnow()
    san = x509.SubjectAlternativeName([
        x509.DNSName('localhost'),
        x509.IPAddress(ipaddress.ip_address('127.0.0.1')),
    ])
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + datetime.timedelta(days=3650))
        .add_extension(san, critical=False)
        .sign(key, hashes.SHA256())
    )
    os.makedirs(os.path.dirname(cert_path) or '.', exist_ok=True)
    with open(key_path, 'wb') as f:
        f.write(key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        ))
    with open(cert_path, 'wb') as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))
    return cert_path, key_path


def build_tls_context(tls_cfg, config_dir):
    """根据 tls 配置段构造 ssl.SSLContext。

    返回 SSLContext 表示可启用 HTTPS；返回 None 表示不应启用（未开启或失败），
    调用方应安全回退到明文 HTTP。
    """
    if not isinstance(tls_cfg, dict) or not tls_cfg.get('enabled'):
        return None

    log = _get_logger()

    cert = _resolve_path(tls_cfg.get('cert_file'), config_dir)
    key = _resolve_path(tls_cfg.get('key_file'), config_dir)

    # 用户未提供证书时，自动生成自签名证书（仅一次）
    if not (cert and key and os.path.exists(cert) and os.path.exists(key)):
        auto_cert = os.path.join(config_dir, 'dbox-selfsigned.crt')
        auto_key = os.path.join(config_dir, 'dbox-selfsigned.key')
        if not (os.path.exists(auto_cert) and os.path.exists(auto_key)):
            try:
                _generate_self_signed(auto_cert, auto_key)
                log.runtime('INFO', '已生成自签名 TLS 证书（默认 10 年，CN=localhost），可后续替换为受信任证书')
            except Exception as e:
                log.runtime('ERROR', f'生成自签名证书失败，回退到明文 HTTP: {e}')
                return None
        cert, key = auto_cert, auto_key

    try:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(cert, key)
        return ctx
    except Exception as e:
        log.runtime('ERROR', f'加载 TLS 证书失败，回退到明文 HTTP: {e}')
        return None
