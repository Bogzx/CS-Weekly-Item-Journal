"""Joining and cleaning EasyOCR fragments (no model needed)."""

import pytest

from Src.ImageDetector.modified_detect_text import is_ui_text, join_fragments


def box(top, left, height=10, width=40):
    return [[left, top], [left + width, top], [left + width, top + height], [left, top + height]]


class TestIsUiText:
    @pytest.mark.parametrize('text', [
        'Requires a purchased key to open', 'Requires a purchased key', 'to open',
        'Requlres a purchascd', 'Kcy to opcn', 'Free',
    ])
    def test_ui_lines(self, text):
        assert is_ui_text(text)

    @pytest.mark.parametrize('text', [
        'Operation Bravo Case', 'Recoil Case', 'Keep the Change (Jungle Green)',
        'Fire', 'Reef', 'Sealed Graffiti | Sorry', '(Bazooka Pink)', 'Nova | Sand Dune',
    ])
    def test_item_text_is_kept(self, text):
        assert not is_ui_text(text)


class TestJoinFragments:
    def test_two_line_graffiti_is_joined_in_reading_order(self):
        fragments = [(box(20, 0), '(Bazooka Pink)', 0.9), (box(0, 0), 'Sealed Graffiti | Sorry', 0.9)]

        assert join_fragments(fragments) == 'Sealed Graffiti | Sorry (Bazooka Pink)'

    def test_fragments_on_one_line_are_read_left_to_right(self):
        fragments = [(box(1, 60), '| Forest DDPAT', 0.9), (box(0, 0), 'Sawed-Off', 0.9)]

        assert join_fragments(fragments) == 'Sawed-Off | Forest DDPAT'

    def test_everything_under_a_case_name_is_dropped(self):
        """The key notice under a case, even garbled beyond the UI filter."""
        fragments = [(box(0, 0), 'Rocoii Caso', 0.9), (box(20, 0), 'Acquiros J purchoscd kcy Honnen', 0.4)]

        assert join_fragments(fragments) == 'Rocoii Caso'

    def test_ui_line_is_dropped(self):
        fragments = [(box(0, 0), 'Nova | Sand Dune', 0.9), (box(40, 0), 'Free', 0.9)]

        assert join_fragments(fragments) == 'Nova | Sand Dune'

    def test_empty(self):
        assert join_fragments([]) == ''
