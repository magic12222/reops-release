"""启动端口分类仅使用替身，不停止或启动任何真实服务。"""
import errno
import json
from pathlib import Path
import runpy
import socket
import sys
from unittest.mock import MagicMock, patch

import pytest

from scripts.run_vikunja_workbench import MonitoringPortInUse, check_monitoring_port


def listener(error=None):
    value=MagicMock()
    value.__enter__.return_value=value
    value.bind.side_effect=error
    return value


def test_free_port_only_checks_fixed_loopback_address():
    value=listener()
    with patch.object(socket,'socket',return_value=value):
        check_monitoring_port()
    value.bind.assert_called_once_with(('127.0.0.1',8021))
    value.listen.assert_not_called()


@pytest.mark.parametrize('windows',[False,True])
def test_occupied_port_has_safe_specific_error(windows):
    error=OSError(errno.EADDRINUSE,'private OS diagnostic')
    if windows:
        error=OSError('private Windows diagnostic')
        error.winerror=10048
    with patch.object(socket,'socket',return_value=listener(error)):
        with pytest.raises(MonitoringPortInUse) as result:
            check_monitoring_port()
    assert str(result.value)==''


def test_other_os_failure_is_not_misreported_as_existing_service():
    error=OSError(errno.EACCES,'test permission failure')
    with patch.object(socket,'socket',return_value=listener(error)):
        with pytest.raises(OSError) as result:
            check_monitoring_port()
    assert result.value is error


def test_cli_explains_occupied_port_before_creating_demo_data(capsys):
    script=Path(__file__).resolve().parents[1]/'scripts/run_vikunja_workbench.py'
    value=listener(OSError(errno.EADDRINUSE,'private OS diagnostic'))
    with patch.object(socket,'socket',return_value=value), \
            patch('workbench.vikunja_target.VikunjaDocker.inspect'), \
            patch('scripts.vikunja_baseline.BusinessSession') as business, \
            patch.object(sys,'argv',[str(script),'--serve','--paused']):
        with pytest.raises(SystemExit) as result:
            runpy.run_path(str(script),run_name='__main__')
    assert result.value.code==1
    response=json.loads(capsys.readouterr().out)
    assert response['error']=='monitoring_port_in_use' and response['port']==8021
    assert '5174/workbench' in response['message']
    assert 'private' not in json.dumps(response)
    business.assert_not_called()
