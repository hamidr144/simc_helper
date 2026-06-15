from unittest.mock import patch

from utils.debug_cli import main


def test_debug_cli_status():
    with patch("requests.get") as mock_get:
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {
            "status": "Idle",
            "active_input": None,
            "workers": [{"name": "W1", "id": "123", "status": "Idle"}]
        }
        
        with patch("sys.argv", ["debug_cli.py", "status"]):
            main()
        assert mock_get.called

def test_debug_cli_stop_sim():
    with patch("requests.post") as mock_post:
        mock_post.return_value.json.return_value = {"message": "Stopped"}
        with patch("sys.argv", ["debug_cli.py", "stop-sim"]):
            main()
        assert mock_post.called

def test_debug_cli_shutdown():
    with patch("requests.post") as mock_post:
        mock_post.return_value.json.return_value = {"status": "shutting down"}
        with patch("sys.argv", ["debug_cli.py", "shutdown"]):
            main()
        assert mock_post.called
