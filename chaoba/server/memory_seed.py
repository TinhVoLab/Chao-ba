"""Simulated memory-book stories and activity log for the three demo personas (all flagged simulated).

Stories are hand-written retellings in each elder's voice (VI) with an English translation, spread over the 90
seeded days, mixed shared / private (the per-story consent the elder gave at the end of that call).
Ông Tư's stories after about day 45 are a little shorter and less specific (fewer names and dates, a few "ờ"),
in line with his slow simulated drift; this is subtle on purpose and is not used by the daily light.

The activity log is generated deterministically from the persona records: one game on two days out of three
(adaptive level, success probability lower during Bà Hạnh's dip around days 33-44 and slowly lower for Ông Tư as his
drift progresses), one habit / social nudge per answered call, and the life-story question on story days.
For Bà Hạnh, the care plan agreed on day 44 (DMAIC Improve) adds a ``care_plan`` row: morning walk and sunlight,
water, regular sleep, calling an old friend; nudges after day 44 favour those.
"""
from __future__ import annotations

import hashlib
import random

# (day, question_id, shared, text_vi, text_en, people [(vi, en)], places)
STORIES: dict[str, list[tuple]] = {
    "hanh": [
        (4, "c1", True,
         "Hồi nhỏ bà hay theo mấy đứa trong xóm ra ruộng bắt cá lia thia, bỏ vô hũ chao nuôi chơi. Chiều nào cũng "
         "đi tới chạng vạng mới về, bị má rầy hoài. Chơi thân nhất là con Tư nhà kế bên, hai đứa đi đâu cũng có nhau.",
         "As a girl I used to follow the village children out to the rice fields to catch fighting fish, and kept them "
         "in an old tofu jar. Every afternoon we stayed out until dusk, and Mother scolded me again and again. My "
         "closest friend was Tư from next door; the two of us went everywhere together.",
         [("má", "my mother"), ("con Tư", "Tư, a childhood friend")], []),
        (11, "f1", True,
         "Món bà nhớ nhất là canh chua bông điên điển má bà nấu mỗi mùa nước nổi. Cá linh tươi rói, me chua, nêm chút "
         "đường, nấu xong cả nhà ngồi ăn với cơm nóng. Giờ bà nấu cho con Lan, nó cũng mê y như bà hồi nhỏ.",
         "The dish I remember most is my mother's sour soup with sesbania flowers, cooked every flood season. Fresh "
         "linh fish, tamarind, a pinch of sugar, and the whole family sat down to eat it with hot rice. Now I cook it "
         "for Lan, and she loves it just as I did as a child.",
         [("má", "my mother"), ("con Lan", "Lan, my daughter")], []),
        (19, "l1", True,
         "Bà gặp ông nhà ở đám cưới người họ hàng bên Mỏ Cày năm 1972. Ổng ngồi đờn kìm, hát vọng cổ nghe mùi lắm, cả "
         "rạp ai cũng nín thở nghe. Ổng hiền, ít nói, mà mỗi lần gặp bà là cười hoài.",
         "I met my husband at a relative's wedding in Mỏ Cày in 1972. He was playing the moon lute and singing vọng cổ "
         "so movingly that the whole tent held its breath. He was gentle and quiet, but every time he saw me he could "
         "not stop smiling.",
         [("ông nhà", "my husband")], ["Mỏ Cày"]),
        (26, "d1", False,
         "Đám cưới bà làm ở nhà, dựng rạp lá dừa trước sân, cả xóm tới phụ làm gà, nấu cà ri. Bà mặc áo dài đỏ má may "
         "cho, tay run quá trời. Ông nhà uống có hai ly mà mặt đỏ tới mang tai.",
         "Our wedding was at home under a coconut-leaf tent in the yard, and the whole hamlet came to help with the "
         "chicken and the curry. I wore a red áo dài my mother sewed, and my hands were shaking terribly. My husband "
         "had only two glasses and went red to the ears.",
         [("má", "my mother"), ("ông nhà", "my husband")], []),
        (37, "h3", True,
         "Mùa nước nổi thì cả xóm bơi xuồng đi thăm nhau, nước lên sát nền nhà. Ba bà giăng lưới bắt cá linh, má làm "
         "mắm, phơi khô để dành ăn cả năm. Tụi nhỏ thì nhảy xuống mương tắm, vui hết biết.",
         "In flood season the whole hamlet paddled boats to visit each other, and the water came right up to the "
         "floor. My father set nets for linh fish and my mother made fish sauce and dried fish to last the year. We "
         "children jumped into the canal to swim; it was the best fun.",
         [("ba", "my father"), ("má", "my mother")], []),
        (48, "w1", True,
         "Hồi trẻ bà bán vải ngoài chợ Mỏ Cày, sáng nào cũng dậy từ bốn giờ chèo xuồng ra chợ. Cực lắm mà nhờ vậy mới "
         "nuôi được con Lan với thằng Minh ăn học. Bà Ba Huệ sạp kế bên hay giữ sạp giùm lúc bà chạy về cho con bú.",
         "As a young woman I sold fabric at the Mỏ Cày market, rowing there at four every morning. It was hard work, "
         "but it is how I put Lan and Minh through school. Mrs Ba Huệ at the next stall often minded mine when I ran "
         "home to feed the baby.",
         [("con Lan", "Lan, my daughter"), ("thằng Minh", "Minh, my son"), ("bà Ba Huệ", "Mrs Ba Huệ, a neighbour at the market")],
         ["chợ Mỏ Cày"]),
        (57, "t1", True,
         "Tết hồi xưa nhà bà gói bánh tét cả đêm, mấy đứa nhỏ ngồi canh nồi bánh tới sáng. Sáng mùng một mặc đồ mới đi "
         "chúc Tết ông bà nội, được lì xì mấy đồng bạc cắc. Bà còn nhớ mùi lá chuối với mùi nhang trên bàn thờ.",
         "At Tết we wrapped bánh tét all night, and we children sat up watching the pot until morning. On the first "
         "morning we put on new clothes to wish our grandparents a happy new year and got a few coins as lucky money. "
         "I still remember the smell of banana leaves and incense on the altar.",
         [("ông bà nội", "my paternal grandparents")], []),
        (66, "k1", False,
         "Hồi ông nhà mất, bà tưởng hổng gượng dậy nổi. Nhờ con Lan về ở với bà mấy tháng, hàng xóm ngày nào cũng ghé. "
         "Bà ra vườn tưới cây mai ổng trồng, coi như ổng còn ở đó.",
         "When my husband passed away I thought I would never get back on my feet. Lan came home to stay with me for a "
         "few months, and the neighbours dropped by every day. I went out to water the apricot tree he planted, as if "
         "he were still there.",
         [("ông nhà", "my husband"), ("con Lan", "Lan, my daughter"), ("hàng xóm", "the neighbours")], []),
        (75, "b3", True,
         "Hồi xưa xóm bà tối nào cũng có đờn ca tài tử dưới gốc me đầu xóm. Ông nhà đờn, bà ca bài Dạ cổ hoài lang, ai "
         "cũng khen. Giờ bà mở radio nghe cải lương là nhớ mấy đêm đó.",
         "In the old days there was đờn ca tài tử music every evening under the tamarind tree at the head of our "
         "hamlet. My husband played and I sang Dạ cổ hoài lang, and everyone praised us. Now when I listen to cải "
         "lương on the radio, I remember those nights.",
         [("ông nhà", "my husband")], []),
        (81, "l3", False,
         "Hồi mới quen, ông nhà tặng bà cây kẹp tóc đồi mồi mua ở chợ Bến Tre. Bà cất trong hộp thiếc, tới giờ vẫn còn. "
         "Chuyện đó bà chưa kể với ai hết.",
         "When we first started courting, my husband gave me a tortoiseshell hair clip he bought at the Bến Tre market. "
         "I kept it in a tin box and I still have it. I have never told anyone about it.",
         [("ông nhà", "my husband")], ["chợ Bến Tre"]),
        (86, "p1", True,
         "Hồi con Lan mới sinh năm 1978, nhà còn nghèo, ông nhà đi làm mướn ngoài đồng. Nó ngoan lắm, bà để nó nằm võng "
         "rồi vừa ru vừa nấu cơm. Giờ nó ở thành phố mà tuần nào cũng gọi về hỏi má ăn cơm chưa.",
         "When Lan was born in 1978 we were still poor, and my husband worked as a hired hand in the fields. She was "
         "such a good baby; I laid her in the hammock and sang lullabies while I cooked. Now she lives in the city, but "
         "every week she calls to ask whether Mother has eaten.",
         [("con Lan", "Lan, my daughter"), ("ông nhà", "my husband")], []),
    ],
    "tu": [
        (3, "w5", True,
         "Năm 1972 tui ra trường sư phạm, được phân về dạy Văn ở trường Lê Quý Đôn. Lớp đầu tiên là lớp mười một, bốn "
         "mươi hai đứa, đứa nào cũng lém. Bài đầu tui giảng Truyện Kiều, đọc đoạn Kiều ở lầu Ngưng Bích mà cả lớp im "
         "phăng phắc. Tới giờ mấy đứa học trò cũ còn ghé thăm tui mỗi ngày hai mươi tháng mười một.",
         "In 1972 I graduated from teachers' college and was posted to teach literature at Lê Quý Đôn school. My first "
         "class was eleventh grade, forty-two pupils, every one a chatterbox. My first lesson was The Tale of Kiều; I "
         "read the passage of Kiều at Ngưng Bích tower and the whole class fell silent. To this day some former pupils "
         "still visit me every 20 November.",
         [("học trò", "my pupils")], ["trường Lê Quý Đôn"]),
        (10, "c2", True,
         "Hồi nhỏ tui học trường làng ở Gò Công, đi chân đất băng qua hai cánh đồng. Thầy Ba dạy tui chữ, nghiêm lắm "
         "mà thương học trò, mùa mưa còn cho tụi tui ngủ lại nhà thầy. Nhờ thầy mà tui mê văn chương, sau này mới đi "
         "làm thầy giáo.",
         "As a boy I went to the village school in Gò Công, walking barefoot across two fields. Teacher Ba taught me "
         "to read and write; he was strict but loved his pupils, and in the rainy season he even let us sleep at his "
         "house. Thanks to him I fell in love with literature and later became a teacher myself.",
         [("thầy Ba", "Teacher Ba")], ["Gò Công"]),
        (17, "l1", True,
         "Tui gặp bà nhà ở nhà sách Khai Trí trên đường Lê Lợi năm 1974. Bả đang kiếm tập thơ Xuân Diệu, tui đứng kế "
         "bên đọc thuộc lòng cho bả nghe một bài. Bả cười, nói ông thầy này nói nhiều quá, vậy mà sáu tháng sau tụi "
         "tui cưới.",
         "I met my wife at the Khai Trí bookshop on Lê Lợi street in 1974. She was looking for a book of Xuân Diệu's "
         "poems, and I stood beside her and recited one from memory. She laughed and said this teacher talks too "
         "much, and yet six months later we were married.",
         [("bà nhà", "my wife")], ["nhà sách Khai Trí, đường Lê Lợi"]),
        (24, "b1", False,
         "Bạn thân nhất của tui là ông Năm Lợi, hai đứa đánh cờ tướng với nhau từ năm 1980 ở quán cà phê đầu hẻm. Ổng "
         "đi pháo đầu, tui lên mã, ván nào cũng cãi nhau tới tối. Ổng mất năm ngoái, giờ tui ngồi quán đó một mình.",
         "My best friend was Mr Năm Lợi; we played Chinese chess together from 1980 at the café at the end of our "
         "alley. He always opened with the central cannon, I with the horse, and every game we argued until dark. He "
         "passed away last year, and now I sit in that café alone.",
         [("ông Năm Lợi", "Mr Năm Lợi, my chess friend")], []),
        (33, "k3", False,
         "Năm 1975 tui đang đi dạy, học trò nghỉ hết mấy tuần. Tui với bà nhà ở căn nhà thuê bên quận ba, ngồi nghe "
         "radio suốt. Rồi trường mở cửa lại, tui đi dạy tiếp, cuộc sống từ từ cũng quen.",
         "In 1975 I was teaching, and the pupils stayed home for several weeks. My wife and I were in our rented house "
         "in District 3, listening to the radio all day. Then the school reopened, I went back to teaching, and little "
         "by little life settled.",
         [("bà nhà", "my wife")], ["quận 3"]),
        (42, "p1", True,
         "Thằng Khoa sinh năm 1979, hồi đó lương thầy giáo ít lắm, bà nhà phải nhận may đồ thêm. Tối tui ẵm nó đi dạo "
         "bờ kè, đọc thơ cho nó nghe. Nó lớn lên học kỹ sư chớ hổng chịu học văn như tui.",
         "Khoa was born in 1979; a teacher's salary was tiny then and my wife took in sewing. In the evenings I carried "
         "him along the canal embankment and recited poems to him. He grew up to study engineering rather than "
         "literature like me.",
         [("thằng Khoa", "Khoa, my son"), ("bà nhà", "my wife")], []),
        (51, "f2", True,
         "Món tủ của tui là cá kho tộ, bà nhà dạy cho. Kho với nước dừa, tiêu nhiều, để lửa riu riu. Thằng Khoa về là "
         "đòi ăn món đó.",
         "My signature dish is fish braised in a clay pot; my wife taught me. You braise it with coconut water and "
         "plenty of pepper on a very low flame. Whenever Khoa comes home he asks for it.",
         [("bà nhà", "my wife"), ("thằng Khoa", "Khoa, my son")], []),
        (60, "t4", False,
         "Đám giỗ ba tui năm nào cũng đông, ờ, họ hàng dưới Gò Công lên. Bà nhà nấu mấy mâm. Tui lo phần cúng.",
         "My father's death anniversary was always crowded; relatives came up from Gò Công. My wife cooked several "
         "trays of food. I took care of the offerings.",
         [("ba", "my father"), ("bà nhà", "my wife")], ["Gò Công"]),
        (69, "h4", True,
         "Chợ Bến Thành hồi xưa tui hay đi với bà nhà. Mua sách cũ, ờ, ở cái đường gần đó. Lâu quá rồi.",
         "In the old days I often went to Bến Thành market with my wife. We bought second-hand books on a street "
         "nearby. It was a long time ago.",
         [("bà nhà", "my wife")], ["chợ Bến Thành"]),
        (78, "w2", True,
         "Tui tự hào nhất là học trò. Có đứa giờ làm hiệu trưởng, ờ, ở trường nào đó bên quận năm. Nó hay về thăm.",
         "What I am proudest of is my pupils. One of them is a headmaster now, at some school over in District 5. He "
         "often comes to visit.",
         [("học trò", "my pupils")], []),
        (87, "t2", True,
         "Tết hồi nhỏ má may cho tui bộ đồ mới màu xanh. Mặc đi chúc Tết, ờ, vui lắm.",
         "At Tết when I was small, Mother sewed me a new blue outfit. I wore it to pay New Year visits, and it was "
         "great fun.",
         [("má", "my mother")], []),
    ],
    "control": [
        (6, "h4", True,
         "Hồi trẻ tui chèo ghe chở khóm ra chợ nổi Cái Răng bán, ba giờ sáng đã đi. Ghe nào bán gì thì treo lên cây bẹo "
         "cho người ta thấy. Bán xong tui ghé ghe hủ tiếu ăn một tô nóng hổi.",
         "As a young man I rowed a boat full of pineapples to the Cái Răng floating market, leaving at three in the "
         "morning. Each boat hung what it sold on a tall pole so buyers could see. After selling I stopped at the "
         "noodle boat for a steaming bowl.",
         [], ["chợ nổi Cái Răng"]),
        (15, "c1", True,
         "Hồi nhỏ tui với thằng Sáu Mập hay thả diều trên bờ đê, diều làm bằng giấy tập cũ. Có bữa diều đứt dây bay qua "
         "bên kia sông, hai đứa bơi qua lượm. Về bị ba rầy mà vẫn khoái.",
         "As a boy I flew kites on the dyke with my friend Sáu Mập; we made them from old exercise-book paper. One day "
         "the string broke and the kite flew across the river, so the two of us swam over to fetch it. Father scolded "
         "us when we got home, but we loved it all the same.",
         [("thằng Sáu Mập", "Sáu Mập, a childhood friend"), ("ba", "my father")], []),
        (23, "w3", True,
         "Tui làm ruộng với nuôi cá suốt đời, sáng ra đồng, chiều cho cá ăn. Cái ao sau nhà tui đào năm 1985, nuôi cá tra "
         "với cá lóc. Năm nào được mùa là cả nhà mừng.",
         "I have farmed rice and raised fish all my life: fields in the morning, feeding the fish in the afternoon. I "
         "dug the pond behind the house in 1985 for pangasius and snakehead. Every good harvest made the whole family "
         "happy.",
         [], []),
        (34, "d3", False,
         "Đám cưới tui hồi xưa đi ghe rước dâu, ba chiếc ghe kết lá dừa. Tới nhà gái thì nước ròng, ghe mắc cạn, cả đám "
         "phải lội bùn lên. Bà nhà tui giờ còn chọc chuyện đó.",
         "At my wedding we fetched the bride by boat, three boats decorated with coconut leaves. When we reached her "
         "house the tide was out, the boats ran aground, and we all had to wade up through the mud. My wife still "
         "teases me about it.",
         [("bà nhà", "my wife")], []),
        (47, "f4", True,
         "Trái cây tui mê nhất là mận hồng đào ở vườn ngoại. Hồi nhỏ leo cây hái, bị kiến vàng cắn sưng tay mà vẫn leo.",
         "My favourite fruit was the rose-apple from my grandmother's orchard. As a boy I climbed the tree to pick "
         "them, and even when the weaver ants bit my hands I kept climbing.",
         [("bà ngoại", "my maternal grandmother")], []),
        (58, "t3", True,
         "Trung thu hồi xưa ba tui làm lồng đèn ông sao bằng tre với giấy kiếng đỏ. Tối rằm tụi nhỏ trong xóm rước đèn "
         "đi vòng vòng, vừa đi vừa hát. Giờ cháu nội tui chơi lồng đèn nhựa có nhạc.",
         "For Mid-Autumn my father made star lanterns from bamboo and red cellophane. On the full-moon night the "
         "children of the hamlet paraded around with them, singing as we went. Now my grandchildren play with plastic "
         "lanterns that play music.",
         [("ba", "my father"), ("cháu nội", "my grandchildren")], []),
        (72, "p2", True,
         "Nuôi con Thảo hồi đó cực, tui với bà nhà thay phiên ra đồng. Nó học giỏi, đi học về là phụ cho cá ăn. Giờ nó "
         "làm cô giáo, chiều nào cũng ghé ăn cơm với tui.",
         "Raising Thảo was hard; my wife and I took turns working the fields. She did well at school and helped feed "
         "the fish when she got home. Now she is a teacher, and she drops by for dinner with me every evening.",
         [("con Thảo", "Thảo, my daughter"), ("bà nhà", "my wife")], []),
        (84, "b2", False,
         "Xóm tui hồi xưa vui nhất là ông Tám Đờn, ổng kể chuyện ma mà ai cũng cười. Đám giỗ nào có ổng là đông. Giờ "
         "ổng chín mươi mấy tuổi rồi.",
         "The liveliest man in our hamlet was Mr Tám Đờn; he told ghost stories that made everyone laugh. Every "
         "remembrance feast he came to was packed. He is in his nineties now.",
         [("ông Tám Đờn", "Mr Tám Đờn, a neighbour")], []),
    ],
}

# DMAIC Improve (Bà Hạnh): activities agreed with the family on the intervention day.
CARE_PLANS = {"hanh": {"day": 44, "focus": ["walk_sun", "water", "sleep", "friend"],
                       "label_vi": "Kế hoạch chăm sóc: đi bộ phơi nắng sáng, uống đủ nước, ngủ đúng giờ, gọi bạn cũ",
                       "label_en": "Care plan: morning walk and sunlight, enough water, regular bedtime, call an old friend"}}


def _ramp(d: int, start: int, length: int) -> float:
    return 0.0 if d < start else min(1.0, (d - start) / length)


def game_success_p(key: str, day: int, level: int) -> float:
    if key == "hanh":
        base = 0.84 - 0.32 * (_ramp(day, 33, 4) * (1 - _ramp(day, 45, 6)))
    elif key == "tu":
        base = 0.86 - 0.28 * _ramp(day, 30, 60)
    else:
        base = 0.85
    return max(0.15, min(0.97, base - 0.12 * (level - 2)))


def rng_for(*parts) -> random.Random:
    return random.Random(int(hashlib.sha256(":".join(map(str, parts)).encode()).hexdigest()[:12], 16))
