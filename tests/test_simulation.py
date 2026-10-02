from simulation.run_simulation import run_simulation


def test_mock_user_driver_simulation():
    result = run_simulation(rider_count=25, driver_count=4)
    assert result["outcomes"] == {"matched": 4, "unmatched": 21}
    assert result["unique_driver_assignments"] == 4