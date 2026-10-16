import numpy as np
import pytest

from voicebench.audio.noise import babble_noise, make_noise, pink_noise, white_noise
from voicebench.audio.signal import (
    fit_length,
    mix_at_snr,
    overlay,
    peak_normalise,
    read_wav,
    resample,
    snr_db,
    write_wav,
)

SR = 16_000


def tone(seconds=1.0, freq=440.0, amp=0.5):
    t = np.arange(int(SR * seconds)) / SR
    return (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)


@pytest.mark.parametrize("target", [5.0, 10.0, 0.0, -3.0])
@pytest.mark.parametrize("kind", ["white", "pink"])
def test_mix_hits_target_snr(target, kind):
    sig = tone()
    _, scaled = mix_at_snr(sig, make_noise(kind, len(sig), seed=1), target)
    assert snr_db(sig, scaled) == pytest.approx(target, abs=1e-3)


def test_mix_is_signal_plus_noise_and_keeps_length():
    sig = tone(0.5)
    mix, scaled = mix_at_snr(sig, white_noise(100, seed=0), 5)  # short noise gets tiled
    assert len(mix) == len(sig)
    np.testing.assert_allclose(mix, sig + scaled, atol=1e-6)


def test_peak_normalise_preserves_snr():
    sig = tone()
    mix, scaled = mix_at_snr(sig, white_noise(len(sig), 3), 5)
    k = 0.9 / np.max(np.abs(mix))
    assert np.max(np.abs(peak_normalise(mix))) == pytest.approx(0.9, rel=1e-5)
    assert snr_db(sig * k, scaled * k) == pytest.approx(5, abs=1e-3)


def test_mix_rejects_silence():
    with pytest.raises(ValueError):
        mix_at_snr(np.zeros(10, np.float32), white_noise(10, 0), 5)
    with pytest.raises(ValueError):
        mix_at_snr(tone(), np.zeros(10, np.float32), 5)


def test_noise_is_deterministic_per_seed():
    np.testing.assert_array_equal(white_noise(1000, 7), white_noise(1000, 7))
    assert not np.array_equal(white_noise(1000, 7), white_noise(1000, 8))
    np.testing.assert_array_equal(pink_noise(1000, 7), pink_noise(1000, 7))


def test_pink_noise_has_more_low_than_high_frequency_energy():
    p = pink_noise(SR * 4, seed=2)
    spec = np.abs(np.fft.rfft(p)) ** 2
    freqs = np.fft.rfftfreq(len(p), 1 / SR)
    low = spec[(freqs > 50) & (freqs < 500)].mean()
    high = spec[(freqs > 4000) & (freqs < 7000)].mean()
    assert low > 10 * high


def test_babble_needs_two_talkers_and_has_unit_std():
    with pytest.raises(ValueError):
        babble_noise([tone()], 100, 0)
    b = babble_noise([tone(0.3, 300), tone(0.7, 520), tone(0.2, 800)], SR, seed=4)
    assert len(b) == SR
    assert np.std(b) == pytest.approx(1.0, rel=1e-3)


def test_unknown_noise_type():
    with pytest.raises(ValueError):
        make_noise("traffic", 10, 0)


def test_fit_length_and_overlay():
    assert len(fit_length(np.ones(3, np.float32), 7)) == 7
    assert len(fit_length(np.ones(9, np.float32), 7)) == 7
    out = overlay(np.ones(4, np.float32), np.ones(4, np.float32), offset=2)
    np.testing.assert_array_equal(out, [1, 1, 2, 2, 1, 1])
    with pytest.raises(ValueError):
        overlay(np.ones(2, np.float32), np.ones(2, np.float32), offset=-1)


def test_resample_and_wav_roundtrip(tmp_path):
    x = tone(1.0)
    y = resample(x, SR, 22_050)
    assert len(y) == 22_050
    path = tmp_path / "a.wav"
    write_wav(path, y, sr=22_050)
    back = read_wav(path)  # resampled to 16 kHz on read
    assert len(back) == SR
    assert np.corrcoef(back[100:-100], x[100:-100])[0, 1] > 0.99
