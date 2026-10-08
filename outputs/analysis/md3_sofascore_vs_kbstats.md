# MD3: derived SofaScore vs KBStats points

Comparison of the nine Bundesliga fixtures played 11–13 September 2026. Difference = derived SofaScore points minus KBStats points. No scaling or calibration applied.

Derived source: `C:\kickbase project\outputs\sofascore\player_kickbase_point_averages\overall_player_kickbase_point_averages_2026-09-16_20-24-15_272946+0200.json`
KBStats source: `C:\kickbase project\outputs\kbstats\players\kbstats_players_20260915_134004_+0200.json`

Method: use each team’s latest Bundesliga match ID from the source team-form snapshot and its individual match_calculations entry. KBStats history[0] is MD3: history[1:] matches the pre-MD3 snapshot for all 461 players present in both snapshots. Join within team using normalized full names and saved SofaScore player-ID cross references; Rael Nakuzola is matched explicitly to Rael-Tshimbela Nakuzola within Mainz. All award sums reconcile with saved derived totals.

Coverage: 264 matched appearances out of 285 KBStats MD3 appearances; all nine fixtures and 18 teams represented. 21 KBStats appearances have no comparable MD3 calculation in the latest derived export. The export applies a minimum-appearance/latest-two-appearances filter; missing records are excluded, never treated as zero.

## Summary

Mean absolute error: 9.38; mean signed error: -6.88; RMSE: 16.43. 21 exact, 199 within 10 points, 240 within 25 points. 173 underestimates and 70 overestimates.

## Patterns and limitations

- All 17 matched goalkeepers are underestimated: mean gap 39.82 points. They account for 677 of the 1,817 net missing points. The snapshot explicitly omits goalkeeper actions including dive saves, catches, collections and keeper sweeper; these are plausible contributors, but KBStats provides totals rather than an action ledger, so the exact causal breakdown cannot be proven.
- Outfield mean absolute error: 7.28 points.
- Position labels differ for 42 matched players. This can matter for position-dependent scoring, but label differences alone do not establish the cause of each residual.
- Amos Pieper’s derived ledger contains a -45 mistake-before-goal deduction; his total discrepancy is -58. This is a specific classification to investigate, not proof that KBStats omitted the deduction.
- Kane’s derived ledger includes +35 for an assist, +80 for a goal and +24 for three blocked shots; Saibari and Olise have no goal or assist award in this match. Their large residuals warrant event-credit checks. KBStats totals alone cannot identify which award differs.
- Zone priors, shot-assist proxies, shot classifications and ignored assist/action categories remain approximation sources.

## By SofaScore position

| Position | Players | Mean signed difference | Mean absolute error |
|---|---:|---:|---:|
| GK | 17 | -39.82 | 39.82 |
| DEF | 74 | -4.28 | 8.50 |
| MID | 111 | -4.54 | 6.63 |
| FWD | 62 | -5.15 | 6.98 |

## Every matched player (largest absolute deviation first)

| Player | Team | Derived | KBStats | Difference |
|---|---|---:|---:|---:|
| Nahuel Noll | SC Paderborn 07 | 75 | 158 | -83 |
| Fabian Bredlow | VfB Stuttgart | 58 | 128 | -70 |
| Oliver Baumann | TSG Hoffenheim | 83 | 149 | -66 |
| Nicolas Kristof | SV 07 Elversberg | 34 | 100 | -66 |
| Karl Hein | SV Werder Bremen | 173 | 234 | -61 |
| Ismael Saibari | FC Bayern München | 120 | 180 | -60 |
| Amos Pieper | SV Werder Bremen | 110 | 168 | -58 |
| Harry Kane | FC Bayern München | 263 | 209 | +54 |
| Loris Karius | FC Schalke 04 | 96 | 147 | -51 |
| Michael Olise | FC Bayern München | 184 | 232 | -48 |
| Moritz Nicolas | Borussia M'gladbach | -14 | 34 | -48 |
| Frederik Rönnow | 1. FC Union Berlin | 52 | 97 | -45 |
| Adam Daghim | TSG Hoffenheim | 154 | 194 | -40 |
| Maarten Vandevoordt | RB Leipzig | 167 | 207 | -40 |
| Finn Dahmen | FC Augsburg | 47 | 86 | -39 |
| Hennes Behrens | FC Augsburg | 121 | 159 | -38 |
| Leopold Querfeld | 1. FC Union Berlin | 80 | 112 | -32 |
| Mark Flekken | Bayer 04 Leverkusen | 38 | 70 | -32 |
| Jordy Makengo | SC Freiburg | 244 | 276 | -32 |
| Maximilian Rohr | SV 07 Elversberg | 80 | 109 | -29 |
| Josha Vagnoman | VfB Stuttgart | 47 | 75 | -28 |
| Soufiane El-Faouzi | FC Schalke 04 | 83 | 110 | -27 |
| Bambasé Conté | TSG Hoffenheim | 77 | 103 | -26 |
| Daniel Heuer Fernandes | Hamburger SV | -6 | 20 | -26 |
| Willi Orban | RB Leipzig | 323 | 300 | +23 |
| Stefano Marino | SC Paderborn 07 | 10 | 32 | -22 |
| Nikola Katic | FC Schalke 04 | 175 | 197 | -22 |
| Robin Zentner | 1. FSV Mainz 05 | 19 | 40 | -21 |
| Shafiq Nandja | Hamburger SV | -54 | -33 | -21 |
| Junior Adamu | FC Schalke 04 | 100 | 121 | -21 |
| Tim Kleindienst | Borussia M'gladbach | -84 | -64 | -20 |
| Tom Rothe | 1. FC Union Berlin | 131 | 150 | -19 |
| Chris Führich | VfB Stuttgart | 41 | 59 | -18 |
| Mats Rots | TSG Hoffenheim | 87 | 105 | -18 |
| Edmond Tapsoba | Bayer 04 Leverkusen | 170 | 188 | -18 |
| Marvin Schwäbe | 1. FC Köln | 71 | 88 | -17 |
| Albian Hajdari | TSG Hoffenheim | 98 | 115 | -17 |
| Valentin Gendrey | TSG Hoffenheim | 39 | 56 | -17 |
| Lukeba Castello Jr. | RB Leipzig | 97 | 80 | +17 |
| Moussa Diaby | Bayer 04 Leverkusen | 109 | 126 | -17 |
| Marcel Sabitzer | Borussia Dortmund | 81 | 98 | -17 |
| Chrislain Matsima | FC Augsburg | 90 | 107 | -17 |
| Jonathan Burkardt | Eintracht Frankfurt | 230 | 246 | -16 |
| Ritsu Dōan | Eintracht Frankfurt | 90 | 106 | -16 |
| Adil Aouchiche | FC Schalke 04 | 166 | 182 | -16 |
| Mario Götze | Eintracht Frankfurt | 79 | 94 | -15 |
| Christopher Nkunku | RB Leipzig | 196 | 211 | -15 |
| Ethan Nwaneri | Borussia Dortmund | 129 | 144 | -15 |
| Eren Sami Dinkçi | SV Werder Bremen | 13 | 28 | -15 |
| Jeremiaha Maluze | Eintracht Frankfurt | 189 | 202 | -13 |
| Matthias Ginter | SC Freiburg | 313 | 326 | -13 |
| Jan-Niklas Beste | SC Freiburg | 112 | 125 | -13 |
| Timo Becker | FC Schalke 04 | 145 | 158 | -13 |
| Marin Ljubičić | 1. FC Union Berlin | -22 | -10 | -12 |
| Lukas Emanuel Petkov | SV 07 Elversberg | 21 | 33 | -12 |
| Ibrahim Maza | Bayer 04 Leverkusen | 59 | 71 | -12 |
| Serhou Guirassy | Borussia Dortmund | 145 | 157 | -12 |
| Jobe Bellingham | Borussia Dortmund | 146 | 158 | -12 |
| Maximilian Beier | Borussia Dortmund | 89 | 101 | -12 |
| Derry Scherhant | SC Freiburg | 116 | 128 | -12 |
| Thijs Dallinga | 1. FC Köln | -30 | -19 | -11 |
| Robin Koch | Eintracht Frankfurt | 148 | 159 | -11 |
| Raphael Obermair | SC Paderborn 07 | 45 | 56 | -11 |
| Facundo Medina | Bayer 04 Leverkusen | 73 | 62 | +11 |
| David Møller Wolfe | Hamburger SV | 0 | 11 | -11 |
| Kim Minjae | FC Bayern München | 139 | 129 | +10 |
| Ramon Hendriks | VfB Stuttgart | 69 | 59 | +10 |
| Otto Ruoppi | 1. FSV Mainz 05 | 37 | 47 | -10 |
| Lukas Pinckert | SV 07 Elversberg | 61 | 71 | -10 |
| Julian Ryerson | Borussia Dortmund | 54 | 64 | -10 |
| Igor Matanović | SC Freiburg | 262 | 272 | -10 |
| Yannik Engelhardt | SC Freiburg | 407 | 397 | +10 |
| Yuito Suzuki | SC Freiburg | 86 | 96 | -10 |
| Calvin Brackelmann | FC Augsburg | 126 | 136 | -10 |
| Robin Gosens | FC Schalke 04 | 176 | 186 | -10 |
| Satoshi Tanaka | FC Schalke 04 | 88 | 98 | -10 |
| Dayot Upamecano | FC Bayern München | 117 | 126 | -9 |
| Jamal Musiala | FC Bayern München | 66 | 75 | -9 |
| Dzenan Pejčinović | VfB Stuttgart | 6 | 15 | -9 |
| Leo Sauer | VfB Stuttgart | -15 | -6 | -9 |
| Marius Bülter | 1. FC Köln | 72 | 81 | -9 |
| Ransford Königsdörffer | 1. FSV Mainz 05 | 22 | 31 | -9 |
| Yussuf Poulsen | Hamburger SV | -10 | -1 | -9 |
| Tom Bischof | FC Bayern München | 116 | 108 | +8 |
| Jeff Chabot | VfB Stuttgart | 89 | 81 | +8 |
| Stefan Posch | 1. FSV Mainz 05 | 70 | 62 | +8 |
| Tjark Scheller | SC Paderborn 07 | 36 | 44 | -8 |
| Antonio Nusa | RB Leipzig | 331 | 339 | -8 |
| David Herold | Borussia M'gladbach | -1 | 7 | -8 |
| Patson Daka | Hamburger SV | 26 | 34 | -8 |
| Vincenzo Grifo | SC Freiburg | 110 | 102 | +8 |
| Olivier Deman | SV Werder Bremen | 109 | 117 | -8 |
| Youri Regeer | SV Werder Bremen | 33 | 25 | +8 |
| Chuki | SV Werder Bremen | 102 | 110 | -8 |
| Hasan Kuruçay | FC Schalke 04 | 92 | 100 | -8 |
| Éric Dina Ebimbe | FC Schalke 04 | 76 | 84 | -8 |
| Alphonso Davies | FC Bayern München | 82 | 89 | -7 |
| Luka Lochoshvili | 1. FC Köln | 51 | 44 | +7 |
| Patrick Wimmer | TSG Hoffenheim | 89 | 96 | -7 |
| Woo-Yeong Jeong | 1. FC Union Berlin | 62 | 69 | -7 |
| Noah Atubolu | Eintracht Frankfurt | 182 | 189 | -7 |
| Santiago Castañeda | SC Paderborn 07 | 82 | 89 | -7 |
| Laurin Curda | SC Paderborn 07 | 29 | 36 | -7 |
| Nicolás Capaldo | Hamburger SV | 8 | 1 | +7 |
| Ozan Kabak | TSG Hoffenheim | 156 | 162 | -6 |
| Wouter Burger | TSG Hoffenheim | 87 | 93 | -6 |
| Livan Burcu | 1. FC Union Berlin | 3 | 9 | -6 |
| Emmanuel Latte Lath | 1. FC Union Berlin | 5 | 11 | -6 |
| Elias Baum | Eintracht Frankfurt | 99 | 105 | -6 |
| Phillip Tietz | 1. FSV Mainz 05 | 123 | 129 | -6 |
| Fabio Gruber | 1. FSV Mainz 05 | 40 | 34 | +6 |
| Sheraldo Becker | 1. FSV Mainz 05 | 48 | 54 | -6 |
| Laurin Ulrich | SC Paderborn 07 | 39 | 45 | -6 |
| Neil El Aynaoui | RB Leipzig | 159 | 153 | +6 |
| Aleix García | Bayer 04 Leverkusen | 157 | 151 | +6 |
| Nicolai Remberg | Hamburger SV | 56 | 50 | +6 |
| Jordan Torunarigha | Hamburger SV | 41 | 47 | -6 |
| Marco Grüll | SV Werder Bremen | 50 | 56 | -6 |
| Fabian Rieder | FC Augsburg | 121 | 127 | -6 |
| Ragnar Ache | 1. FC Köln | 21 | 26 | -5 |
| Mikey Moore | 1. FC Köln | 55 | 60 | -5 |
| Leon Avdullahu | TSG Hoffenheim | 87 | 82 | +5 |
| Aljoscha Kemlein | 1. FC Union Berlin | 1 | 6 | -5 |
| Marvin Pieringer | SC Paderborn 07 | 4 | 9 | -5 |
| Benjamin Henrichs | RB Leipzig | 106 | 111 | -5 |
| Franck Honorat | Borussia M'gladbach | 23 | 28 | -5 |
| Joseph Scally | Borussia M'gladbach | -9 | -4 | -5 |
| Lasse Günther | SV 07 Elversberg | 10 | 15 | -5 |
| Patrik Schick | Bayer 04 Leverkusen | 126 | 131 | -5 |
| Miguel Gutiérrez | Bayer 04 Leverkusen | 90 | 95 | -5 |
| Albert Grønbæk | Hamburger SV | 27 | 32 | -5 |
| Michael Gregoritsch | FC Augsburg | 252 | 257 | -5 |
| Dejan Ljubičić | FC Schalke 04 | 44 | 49 | -5 |
| Lennart Karl | FC Bayern München | 190 | 186 | +4 |
| Jamie Leweling | VfB Stuttgart | -14 | -10 | -4 |
| Ísak Jóhannesson | 1. FC Köln | 8 | 12 | -4 |
| Tom Krauß | 1. FC Köln | 71 | 67 | +4 |
| Felix Uduokhai | 1. FC Union Berlin | 71 | 75 | -4 |
| Kacper Potulski | 1. FSV Mainz 05 | 2 | -2 | +4 |
| Jano ter Horst | SC Paderborn 07 | 68 | 64 | +4 |
| Ridle  Baku | RB Leipzig | 68 | 64 | +4 |
| Kevin Stöger | Borussia M'gladbach | 11 | 7 | +4 |
| Kevin Diks | Borussia M'gladbach | 6 | 10 | -4 |
| Lukasz Poreba | SV 07 Elversberg | 50 | 46 | +4 |
| Waldemar Anton | Borussia Dortmund | 136 | 140 | -4 |
| Fábio Silva | Borussia Dortmund | 150 | 154 | -4 |
| Albert Sambi Lokonga | Hamburger SV | 2 | -2 | +4 |
| Maximilian Eggestein | SC Freiburg | 236 | 232 | +4 |
| Philipp Lienhart | SC Freiburg | 187 | 183 | +4 |
| Niclas Füllkrug | SV Werder Bremen | 148 | 152 | -4 |
| Dariusz Stalmach | SV Werder Bremen | 12 | 16 | -4 |
| Cédric Itten | SV Werder Bremen | 7 | 11 | -4 |
| Joshua Kimmich | FC Bayern München | 89 | 92 | -3 |
| Ermedin Demirović | VfB Stuttgart | 4 | 7 | -3 |
| Bilal El Khannouss | VfB Stuttgart | 17 | 20 | -3 |
| Jahmai Simpson-Pusey | 1. FC Köln | 88 | 85 | +3 |
| Gideon Mensah | 1. FC Köln | 56 | 53 | +3 |
| Ellyes Skhiri | 1. FC Köln | 159 | 156 | +3 |
| Andrej Kramarić | TSG Hoffenheim | 20 | 23 | -3 |
| András Schäfer | 1. FC Union Berlin | 44 | 47 | -3 |
| Kaishu Sano | 1. FSV Mainz 05 | 102 | 99 | +3 |
| Mattes Hansen | SC Paderborn 07 | 47 | 44 | +3 |
| Oliver Batista Meier | SC Paderborn 07 | -4 | -7 | +3 |
| Rayan Philippe | SC Paderborn 07 | -17 | -14 | -3 |
| Hugo Bolin | Borussia M'gladbach | -10 | -7 | -3 |
| Jan Gyamerah | SV 07 Elversberg | 25 | 28 | -3 |
| Noah Darvich | SV 07 Elversberg | 26 | 29 | -3 |
| Jarell Quansah | Bayer 04 Leverkusen | 42 | 39 | +3 |
| Joane Gadou | Borussia Dortmund | 114 | 111 | +3 |
| Gregor Kobel | Borussia Dortmund | 95 | 98 | -3 |
| Arthur | SV Werder Bremen | 57 | 54 | +3 |
| Arijon Ibrahimović | FC Augsburg | 45 | 48 | -3 |
| Kenan Karaman | FC Schalke 04 | 82 | 85 | -3 |
| Luis Díaz | FC Bayern München | 72 | 74 | -2 |
| Nathaniel Brown | FC Bayern München | 76 | 74 | +2 |
| Grischa Prömel | VfB Stuttgart | 47 | 49 | -2 |
| Alessio Castro-Montes | 1. FC Köln | 42 | 44 | -2 |
| Tim Lemperle | TSG Hoffenheim | 70 | 72 | -2 |
| Rani Khedira | 1. FC Union Berlin | 30 | 32 | -2 |
| Janik Haberer | 1. FC Union Berlin | -4 | -6 | +2 |
| Younes Ebnoutalib | Eintracht Frankfurt | 9 | 11 | -2 |
| Philipp Mwene | 1. FSV Mainz 05 | -1 | 1 | -2 |
| Danny Da Costa | 1. FSV Mainz 05 | -2 | -4 | +2 |
| Gabriel Vidović | SC Paderborn 07 | 25 | 27 | -2 |
| Clemens Lippmann | SC Paderborn 07 | -25 | -23 | -2 |
| Tidiam Gomis | RB Leipzig | 188 | 190 | -2 |
| Ko Itakura | Borussia M'gladbach | 18 | 16 | +2 |
| Isac Lidberg | Borussia M'gladbach | -19 | -17 | -2 |
| Maurice Krattenmacher | SV 07 Elversberg | 99 | 101 | -2 |
| Felix Keidel | SV 07 Elversberg | 32 | 30 | +2 |
| Christian Kofane | Bayer 04 Leverkusen | 142 | 144 | -2 |
| Daniel Svensson | Borussia Dortmund | 140 | 142 | -2 |
| Felix Nmecha | Borussia Dortmund | 277 | 275 | +2 |
| Joey Veerman | Borussia Dortmund | 99 | 101 | -2 |
| Zakaria El Ouahdi | Hamburger SV | 12 | 14 | -2 |
| Terem Moffi | Hamburger SV | 3 | 5 | -2 |
| Cyriaque Irié | SC Freiburg | 28 | 30 | -2 |
| Philipp Treu | SC Freiburg | 105 | 103 | +2 |
| Mio Backhaus | SC Freiburg | 142 | 144 | -2 |
| Ludovit Reis | SV Werder Bremen | 62 | 60 | +2 |
| Han-Noah Massengo | FC Augsburg | 38 | 36 | +2 |
| Marius Wolf | FC Augsburg | 38 | 36 | +2 |
| Robin Fellhauer | FC Augsburg | 42 | 44 | -2 |
| Young-Woo Seol | FC Augsburg | 1 | -1 | +2 |
| Yannik Keitel | FC Augsburg | 0 | -2 | +2 |
| Maximilian Wöber | FC Schalke 04 | 161 | 163 | -2 |
| Aleksandar Pavlović | FC Bayern München | 250 | 249 | +1 |
| Josip Stanišić | FC Bayern München | 119 | 118 | +1 |
| Maximilian Mittelstädt | VfB Stuttgart | 227 | 226 | +1 |
| Deniz Undav | VfB Stuttgart | -18 | -17 | -1 |
| Linton Maina | 1. FC Köln | 144 | 145 | -1 |
| Adam Hložek | TSG Hoffenheim | 271 | 270 | +1 |
| Vladimír Coufal | TSG Hoffenheim | 61 | 62 | -1 |
| Josip Juranović | 1. FC Union Berlin | 71 | 72 | -1 |
| Michel Aebischer | 1. FC Union Berlin | 23 | 22 | +1 |
| Keita Kosugi | Eintracht Frankfurt | 100 | 101 | -1 |
| Lilian Brassier | Eintracht Frankfurt | 129 | 128 | +1 |
| Raphael Onyedika | Eintracht Frankfurt | 13 | 12 | +1 |
| Nadiem Amiri | 1. FSV Mainz 05 | -22 | -23 | +1 |
| Jae-Sung Lee | 1. FSV Mainz 05 | 8 | 9 | -1 |
| Anthony Caci | 1. FSV Mainz 05 | 4 | 3 | +1 |
| Rael-Tshimbela Nakuzola | 1. FSV Mainz 05 | 30 | 31 | -1 |
| Steffen Tigges | SC Paderborn 07 | -15 | -14 | -1 |
| David Raum | RB Leipzig | 182 | 181 | +1 |
| Ezechiel Banzuzi | RB Leipzig | 164 | 165 | -1 |
| Assan Ouédraogo | RB Leipzig | 60 | 61 | -1 |
| Wael Mohya | Borussia M'gladbach | -17 | -16 | -1 |
| Robin Hack | Borussia M'gladbach | 6 | 5 | +1 |
| Mathieu Nguefack | Borussia M'gladbach | -18 | -19 | +1 |
| David Mokwa | SV 07 Elversberg | 6 | 5 | +1 |
| Noel Futkeu | SV 07 Elversberg | -10 | -9 | -1 |
| Ezequiél Fernández | Bayer 04 Leverkusen | 97 | 98 | -1 |
| Afonso Moreira | Bayer 04 Leverkusen | 78 | 77 | +1 |
| Lucas Vázquez | Bayer 04 Leverkusen | 16 | 17 | -1 |
| Otto Stange | Hamburger SV | -16 | -15 | -1 |
| Fábio Vieira | Hamburger SV | -8 | -9 | +1 |
| Lukas Kübler | SC Freiburg | 23 | 22 | +1 |
| Lucas Höler | SC Freiburg | 32 | 33 | -1 |
| Keisuke Goto | SC Freiburg | 47 | 48 | -1 |
| Marco Friedl | SV Werder Bremen | 110 | 109 | +1 |
| Paul Erevbenagie | SV Werder Bremen | 13 | 12 | +1 |
| Rodrigo Ribeiro | FC Augsburg | -3 | -4 | +1 |
| Mert Kömür | FC Augsburg | 21 | 20 | +1 |
| Angelo Stiller | VfB Stuttgart | 1 | 1 | +0 |
| Finn Jeltsch | VfB Stuttgart | 71 | 71 | +0 |
| Said El Mala | 1. FC Köln | 16 | 16 | +0 |
| Paul Okon-Engstler | 1. FC Köln | -5 | -5 | +0 |
| Tim Skarke | 1. FC Union Berlin | 137 | 137 | +0 |
| Can Uzun | Eintracht Frankfurt | 279 | 279 | +0 |
| Ayoube Amaimouni | Eintracht Frankfurt | 12 | 12 | +0 |
| Timothy Chandler | Eintracht Frankfurt | 21 | 21 | +0 |
| Brajan Gruda | RB Leipzig | 123 | 123 | +0 |
| Philipp Sander | Borussia M'gladbach | -8 | -8 | +0 |
| Francis Onyeka | SV 07 Elversberg | -25 | -25 | +0 |
| Cole Campbell | SV 07 Elversberg | -5 | -5 | +0 |
| Luca Schnellbacher | SV 07 Elversberg | -3 | -3 | +0 |
| Amara Condé | SV 07 Elversberg | -16 | -16 | +0 |
| Malik Tillman | Bayer 04 Leverkusen | 58 | 58 | +0 |
| Carney Chukwuemeka | Borussia Dortmund | 35 | 35 | +0 |
| Bakery Jatta | Hamburger SV | -14 | -14 | +0 |
| Mick Schmetgens | SV Werder Bremen | 6 | 6 | +0 |
| Noahkai Banks | FC Augsburg | 86 | 86 | +0 |
| Alexis Claude-Maurice | FC Augsburg | 10 | 10 | +0 |
| Edin Džeko | FC Schalke 04 | 16 | 16 | +0 |

## Missing from comparison

| Player | Team | KBStats MD3 |
|---|---|---:|
| Jonas Urbig | bayern | 83 |
| Yanik Spalt | stuttgart | 20 |
| Martin Terrier | leverkusen | 21 |
| Guéla Doué | leverkusen | 40 |
| Sebastian Sebulonsen | koeln | 18 |
| Fisnik Asllani | hoffenheim | 48 |
| Koki Machida | hoffenheim | 49 |
| Robert Skov | union | -12 |
| Noël Aséko | frankfurt | 58 |
| Benedict Hollerbach | mainz | 7 |
| Luka Duric | paderborn | -16 |
| Max Finkgräfe | leipzig | 28 |
| Rômulo | leipzig | 143 |
| Maxime Estève | leipzig | 51 |
| Shuto Machino | gladbach | -7 |
| Nico Schlotterbeck | dortmund | 136 |
| Ramy Bensebaini | dortmund | 49 |
| Warmed Omari | hamburg | -59 |
| Mitchell Weiser | bremen | 13 |
| Hee-Chan Hwang | schalke | 82 |
| Janik Bachmann | schalke | 17 |
