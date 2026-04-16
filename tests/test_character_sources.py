import unittest

from ytmanager.character_sources import (
    SOURCE_CATALOG,
    parse_endfield_wiki_cards,
    parse_hoyodb_hsr_cards,
    parse_namu_hsr_cards,
    parse_namu_ww_cards,
    parse_zzz_gg_cards,
)


class CharacterSourceTests(unittest.TestCase):
    def test_parse_zzz_gg_cards(self):
        html = '''
        <li class="item"><a href="/ko/characters/엘렌"><div class="image">
        <img alt="엘렌"><img alt="얼음 속성"><img alt="강공"><img src="/images/ItemRarityS.png">
        </div><div class="name">엘렌</div></a></li>
        '''
        entries = parse_zzz_gg_cards(html, SOURCE_CATALOG["zzz_gg_ko"])
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].canonical_name_ko, "엘렌")
        self.assertEqual(entries[0].element, "얼음")
        self.assertEqual(entries[0].role_or_path, "강공")
        self.assertEqual(entries[0].rarity, "S")

    def test_parse_hoyodb_hsr_cards(self):
        html = '''
        <a href="/ko/starrail/characters/1407"><img src="https://wikistatic/hsr/assets/UI/avatar/medium/1407.png" alt="카스토리스" class="absolute inset-0">
        <img src="IconAttributeQuantum.png"><img src="IconProfessionMemorySmall.png">
        <span class="iconify i-heroicons:star-solid"></span><span class="iconify i-heroicons:star-solid"></span><span class="iconify i-heroicons:star-solid"></span><span class="iconify i-heroicons:star-solid"></span><span class="iconify i-heroicons:star-solid"></span>
        <p class="text-center">카스토리스</p></a>
        '''
        entries = parse_hoyodb_hsr_cards(html, SOURCE_CATALOG["hoyodb_hsr_ko"])
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].canonical_name_ko, "카스토리스")
        self.assertEqual(entries[0].element, "양자")
        self.assertEqual(entries[0].role_or_path, "기억")
        self.assertEqual(entries[0].rarity, "5")

    def test_parse_endfield_wiki_cards(self):
        html = '''
        <a href="/characters/laevatain" class="character-card">
        <img src="/images/characters/laevatain.webp" alt="Laevatain">
        <div class="rarity-badge" data-rarity="6"> ★★★★★★ </div>
        <h3 class="character-name">Laevatain</h3>
        <span class="element-badge"> Heat </span>
        <span class="class-badge">Striker</span>
        </a>
        '''
        entries = parse_endfield_wiki_cards(html, SOURCE_CATALOG["endfield_wiki_en"])
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].canonical_name_ko, "Laevatain")
        self.assertEqual(entries[0].canonical_name_en, "Laevatain")
        self.assertEqual(entries[0].element, "열")
        self.assertEqual(entries[0].role_or_path, "Striker")
        self.assertEqual(entries[0].rarity, "6")

    def test_parse_namu_hsr_cards(self):
        html = """
        <a class='V2nYnWpb' href='/w/%EC%B9%B4%EC%8A%A4%ED%86%A0%EB%A6%AC%EC%8A%A4' title='카스토리스(붕괴: 스타레일)'>
        <img alt='양자 속성'><img alt='기억 운명의 길'>
        <br>카스토리스(붕괴: 스타레일)<br><span>✦✦✦✦✦</span></a>
        """
        entries = parse_namu_hsr_cards(html, SOURCE_CATALOG["namu_hsr_ko"])
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].canonical_name_ko, "카스토리스")
        self.assertIn("카스토리스(붕괴: 스타레일)", entries[0].aliases_ko)
        self.assertEqual(entries[0].element, "양자")
        self.assertEqual(entries[0].role_or_path, "기억")
        self.assertEqual(entries[0].rarity, "5")

    def test_parse_namu_ww_cards(self):
        html = """
        <a class='V2nYnWpb' href='/w/%EA%B8%88%ED%9D%AC' title='금희(명조: 워더링 웨이브)'>
        <img alt='명조 금희(명조: 워더링 웨이브) 아이콘'><img alt='명조 속성-회절'>
        <br><strong><span>금희(명조: 워더링 웨이브)</span></strong><br><span>✦✦✦✦✦</span></a>
        """
        entries = parse_namu_ww_cards(html, SOURCE_CATALOG["namu_ww_ko"])
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].canonical_name_ko, "금희")
        self.assertIn("금희(명조: 워더링 웨이브)", entries[0].aliases_ko)
        self.assertEqual(entries[0].element, "회절")
        self.assertEqual(entries[0].rarity, "5")


if __name__ == "__main__":
    unittest.main()
