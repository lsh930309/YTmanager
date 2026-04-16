//Template: combat//
{[tags]}
[{game_version} {game_content_name} {game_content_season_in_current_version}]

//Section Start//
*{optional: stage_number} {boss_name} - {party_composition}*
- {party[i].canonical_name} {party[i].status_label}
//Section End//

optional: -------------------

{optional: [timestamps]}

############################################

//Template: gacha//
{[tags]}
[{game_version} {pickup_character_name} 가챠]
- 캐릭터 스택: {character_is_guaranteed} {character_stack}
- {equipment_type} 스택: {equipment_is_guaranteed} {equipment_stack}

optional: -------------------

{optional: [timestamps]}

############################################

//Template: freeform//
{[tags]}
{body}

optional: -------------------

{optional: [timestamps]}
