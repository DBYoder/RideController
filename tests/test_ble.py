from ridecontroller.ble import DiscoveredController, classify_advertisement
from ridecontroller.constants import ZWIFT_COMPANY_ID, ZWIFT_RIDE_SERVICE_UUID


def test_ride_is_identified_from_manufacturer_data():
    is_zwift, device_type = classify_advertisement(
        "Zwift Ride", {ZWIFT_COMPANY_ID: b"\x08\x01"}, [ZWIFT_RIDE_SERVICE_UUID]
    )
    assert is_zwift
    assert device_type == "ride_left"


def test_right_half_is_identified():
    _, device_type = classify_advertisement("", {ZWIFT_COMPANY_ID: b"\x07"}, [])
    assert device_type == "ride_right"


def test_play_controllers_are_recognised_but_not_ride():
    _, device_type = classify_advertisement("Zwift Play", {ZWIFT_COMPANY_ID: b"\x03"}, [])
    assert device_type == "play_left"
    assert not DiscoveredController("x", "Zwift Play", device_type).is_ride


def test_service_uuid_alone_is_enough_to_flag_a_zwift_device():
    is_zwift, device_type = classify_advertisement("", {}, [ZWIFT_RIDE_SERVICE_UUID])
    assert is_zwift
    assert device_type is None


def test_name_fallback_when_the_adapter_hides_manufacturer_data():
    is_zwift, device_type = classify_advertisement("Zwift Ride Left", {}, [])
    assert is_zwift
    assert device_type == "ride_left"


def test_unrelated_devices_are_ignored():
    is_zwift, device_type = classify_advertisement("Wahoo KICKR", {89: b"\x01"}, [])
    assert not is_zwift
    assert device_type is None


def test_unknown_zwift_model_byte_leaves_the_type_unset():
    is_zwift, device_type = classify_advertisement("", {ZWIFT_COMPANY_ID: b"\x99"}, [])
    assert is_zwift
    assert device_type is None


def test_label_is_human_readable():
    controller = DiscoveredController("AA:BB:CC", "Zwift Ride", "ride_left", -55)
    assert controller.label() == "Zwift Ride [AA:BB:CC] type=ride_left rssi=-55 dBm"
