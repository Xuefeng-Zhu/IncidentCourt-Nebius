"""Network and credential guard for the provider-free bootstrap image."""
import socket


def reject_credentials(env):
    if any(key.startswith('NEBIUS_') or key == 'JUDGE_ACCESS_CODE' for key in env):
        raise ValueError('Bootstrap refuses provider and judge credential variables.')


def block_outbound():
    def deny(*args, **kwargs):
        raise OSError('Outbound connections are disabled in the bootstrap process.')
    socket.socket.connect = deny
    socket.socket.connect_ex = deny
    socket.create_connection = deny
