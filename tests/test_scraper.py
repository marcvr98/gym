import unittest

from selenium_scraper import find_next_endurance_occupation


class FindNextEnduranceOccupationTests(unittest.TestCase):
    def test_handles_alternative_dom_structure(self):
        html = '''
        <html>
          <body>
            <div id="clasesDiaSel">
              <div class="session-card">
                <span class="time-slot">19:15 - 20:15</span>
                <span class="class-name">ENDURANCE</span>
                <div class="rvMarginDesc">
                  <span class="rvOcupacion">9/16</span>
                </div>
              </div>
            </div>
          </body>
        </html>
        '''

        self.assertEqual(find_next_endurance_occupation(html), '9/16')


if __name__ == "__main__":
    unittest.main()
