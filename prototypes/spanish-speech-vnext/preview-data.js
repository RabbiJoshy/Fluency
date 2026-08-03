window.SPEECH_PREVIEW_DATA = {
  "schemaVersion": 1,
  "prototype": true,
  "generatedAt": "2026-08-03T16:21:35.418842+00:00",
  "sourceRun": "Data/Spanish/Intermediates/speech_mode_evidence/runs/2026-08-03_v0_1",
  "method": {
    "senseAuthority": "SpanishDict stable leaf sense IDs",
    "prominence": "25 seeded random OpenSubtitles occurrences per word; high-confidence unique assignments only",
    "canonicalExamples": "SpanishDict examples already attached to each leaf sense",
    "corpusExamples": "Model-matched candidates requiring independent audit"
  },
  "words": [
    {
      "id": "banco|banco|NOUN",
      "surface": "banco",
      "headword": "banco",
      "pos": "NOUN",
      "spanishDictUrl": "https://www.spanishdict.com/translate/banco",
      "sampled": 25,
      "accepted": 25,
      "coverage": 1.0,
      "abstained": 0,
      "belowGate": 0,
      "prominenceStatus": "usable_first_pass",
      "note": {
        "verdict": "clean_signal",
        "headline": "A clean first-pass result",
        "detail": "All 25 sampled uses received a high-confidence unique sense, strongly favoring the financial sense."
      },
      "importantSenses": [
        {
          "id": "18e",
          "translation": "bank",
          "context": "finance",
          "regions": [],
          "prominence": "dominant",
          "acceptedCount": 22,
          "shareOfSample": 0.88,
          "canonicalExample": {
            "spanish": "Fui al banco a pedir un préstamo.",
            "english": "I went to the bank to ask for a loan."
          },
          "corpusCandidates": [
            {
              "id": "occ-f9d4d75a2006d810",
              "spanish": "Lo malo es que en lugar de ayudar a la gente, ese dinero se va a un banco suizo a nombre de Farrago.",
              "english": "Yeah, trouble is instead of helping the people, Those profits go into a Swiss bank in the name of Farrago.",
              "modelConfidence": "high",
              "modelReason": "Refers to a financial institution (Swiss bank).",
              "review": {
                "status": "unaudited"
              },
              "source": {
                "corpus": "OpenSubtitles en-es",
                "corpusLine": 2166347,
                "spanishDocument": "es/1950/42352/4134621.xml.gz",
                "spanishSegment": "471"
              }
            },
            {
              "id": "occ-7bd1cc34ea4c82fc",
              "spanish": "Los mejores pasaportes se hacen con el Banco de Inglaterra.",
              "english": "The best passports are made by the Bank of England.",
              "modelConfidence": "high",
              "modelReason": "Refers to the Bank of England.",
              "review": {
                "status": "unaudited"
              },
              "source": {
                "corpus": "OpenSubtitles en-es",
                "corpusLine": 2840927,
                "spanishDocument": "es/1955/47818/5469858.xml.gz",
                "spanishSegment": "1203"
              }
            },
            {
              "id": "occ-a4c1acb40e5d9329",
              "spanish": "Aun cuando asaltamos el banco y nos perseguían... no montó el sábado. ¡ No señor!",
              "english": "Why, even when we robbed the bank and the posse was chasing us... he wouldn't ride on Saturday. No sirree!",
              "modelConfidence": "high",
              "modelReason": "Refers to robbing a financial institution.",
              "review": {
                "status": "unaudited"
              },
              "source": {
                "corpus": "OpenSubtitles en-es",
                "corpusLine": 7831967,
                "spanishDocument": "es/1979/79180/6398223.xml.gz",
                "spanishSegment": "788"
              }
            },
            {
              "id": "occ-bb7552691c284b5f",
              "spanish": "Cuando pienso que robaba bancos.",
              "english": "When I think I used to do banks.",
              "modelConfidence": "high",
              "modelReason": "Refers to robbing banks.",
              "review": {
                "status": "unaudited"
              },
              "source": {
                "corpus": "OpenSubtitles en-es",
                "corpusLine": 11710413,
                "spanishDocument": "es/1992/105017/4199910.xml.gz",
                "spanishSegment": "2027"
              }
            }
          ]
        },
        {
          "id": "64a",
          "translation": "bench",
          "context": "seat",
          "regions": [],
          "prominence": "occasional",
          "acceptedCount": 2,
          "shareOfSample": 0.08,
          "canonicalExample": {
            "spanish": "Los bancos del parque están recién pintados.",
            "english": "The park benches have just been painted."
          },
          "corpusCandidates": [
            {
              "id": "occ-72d6aa11aff9a6a0",
              "spanish": "Nos sentamos en un banco Tomamos comida basura",
              "english": "We sat on a bench. We ate fast food.",
              "modelConfidence": "high",
              "modelReason": "Refers to a park bench.",
              "review": {
                "status": "unaudited"
              },
              "source": {
                "corpus": "OpenSubtitles en-es",
                "corpusLine": 36309605,
                "spanishDocument": "es/2010/1654987/3735840.xml.gz",
                "spanishSegment": "887"
              }
            },
            {
              "id": "occ-ac3f7f411ff7804a",
              "spanish": "Ponedlas en este banco.",
              "english": "Just place 'em on the bench here.",
              "modelConfidence": "high",
              "modelReason": "Refers to a bench seat.",
              "review": {
                "status": "unaudited"
              },
              "source": {
                "corpus": "OpenSubtitles en-es",
                "corpusLine": 46808629,
                "spanishDocument": "es/2013/2634294/4797749.xml.gz",
                "spanishSegment": "868"
              }
            }
          ]
        },
        {
          "id": "807",
          "translation": "pew",
          "context": "seat",
          "regions": [],
          "prominence": "occasional",
          "acceptedCount": 1,
          "shareOfSample": 0.04,
          "canonicalExample": {
            "spanish": "La iglesia se ve vacía sin los bancos.",
            "english": "The church looks empty without the pews."
          },
          "corpusCandidates": [
            {
              "id": "occ-4bc60d5042daf032",
              "spanish": "Había enviado un carpintero para medir el banco para ver si podía modificarse para acomodarla.",
              "english": "She had sent a carpenter to measure the front pew... in case it might be altered to accommodate her.",
              "modelConfidence": "high",
              "modelReason": "Refers to a church pew.",
              "review": {
                "status": "unaudited"
              },
              "source": {
                "corpus": "OpenSubtitles en-es",
                "corpusLine": 11981874,
                "spanishDocument": "es/1993/106226/5751796.xml.gz",
                "spanishSegment": "786"
              }
            }
          ]
        }
      ],
      "otherSenses": [
        {
          "id": "18e6",
          "translation": "bank",
          "context": "stock",
          "regions": [],
          "prominence": "uncommon_or_unseen",
          "acceptedCount": 0,
          "shareOfSample": 0.0,
          "canonicalExample": {
            "spanish": "El banco de sangre necesita donantes de todo tipo de sangre.",
            "english": "The blood bank needs donors of all blood types."
          },
          "corpusCandidates": []
        },
        {
          "id": "18e63",
          "translation": "bank",
          "context": "mound",
          "regions": [],
          "prominence": "uncommon_or_unseen",
          "acceptedCount": 0,
          "shareOfSample": 0.0,
          "canonicalExample": {
            "spanish": "Aquí la vegetación acuática incluye bancos de algas.",
            "english": "The aquatic vegetation here includes banks of seaweed."
          },
          "corpusCandidates": []
        },
        {
          "id": "63b",
          "translation": "stool",
          "context": "seat",
          "regions": [],
          "prominence": "uncommon_or_unseen",
          "acceptedCount": 0,
          "shareOfSample": 0.0,
          "canonicalExample": {
            "spanish": "¿Me pasas un banco para bajar ese libro del estante de arriba?",
            "english": "Can you pass me a stool to get that book down from the top shelf?"
          },
          "corpusCandidates": []
        },
        {
          "id": "9e6",
          "translation": "school",
          "context": "group of fish",
          "regions": [],
          "prominence": "uncommon_or_unseen",
          "acceptedCount": 0,
          "shareOfSample": 0.0,
          "canonicalExample": {
            "spanish": "La zona atrae a muchos visitantes porque las aguas cristalinas dejan ver bancos de peces tropicales.",
            "english": "Many visitors are attracted to the area because schools of tropical fish can be seen in the crystal-clear waters."
          },
          "corpusCandidates": []
        },
        {
          "id": "b1c",
          "translation": "workbench",
          "context": "seat",
          "regions": [],
          "prominence": "uncommon_or_unseen",
          "acceptedCount": 0,
          "shareOfSample": 0.0,
          "canonicalExample": {
            "spanish": "Necesito un banco más grande para trabajar en el taller.",
            "english": "I need a larger workbench to work on in the workshop."
          },
          "corpusCandidates": []
        },
        {
          "id": "c83",
          "translation": "desk",
          "context": "seat",
          "regions": [],
          "prominence": "uncommon_or_unseen",
          "acceptedCount": 0,
          "shareOfSample": 0.0,
          "canonicalExample": {
            "spanish": "El colegio ha renovado todos los bancos.",
            "english": "The school has replaced all the desks."
          },
          "corpusCandidates": []
        },
        {
          "id": "f9e",
          "translation": "shoal",
          "context": "group of fish",
          "regions": [],
          "prominence": "uncommon_or_unseen",
          "acceptedCount": 0,
          "shareOfSample": 0.0,
          "canonicalExample": {
            "spanish": "Vimos un banco de atunes mientras buceábamos.",
            "english": "We saw a shoal of tuna while we were diving."
          },
          "corpusCandidates": []
        }
      ]
    },
    {
      "id": "cola|cola|NOUN",
      "surface": "cola",
      "headword": "cola",
      "pos": "NOUN",
      "spanishDictUrl": "https://www.spanishdict.com/translate/cola",
      "sampled": 25,
      "accepted": 19,
      "coverage": 0.76,
      "abstained": 6,
      "belowGate": 0,
      "prominenceStatus": "usable_first_pass",
      "note": {
        "verdict": "known_risk",
        "headline": "Useful counts, unsafe examples",
        "detail": "The broad tail-versus-line split is plausible, but several figurative body uses were confidently attached to the literal tail sense."
      },
      "importantSenses": [
        {
          "id": "237",
          "translation": "tail",
          "context": "animal anatomy",
          "regions": [],
          "prominence": "dominant",
          "acceptedCount": 13,
          "shareOfSample": 0.52,
          "canonicalExample": {
            "spanish": "Milo mueve la cola cuando me escucha entrar.",
            "english": "Milo wags his tail when he hears me come in."
          },
          "corpusCandidates": [
            {
              "id": "occ-d8fab34407dc7ec0",
              "spanish": "Quizás prefieras que te patee la cola.",
              "english": "Rather have your tail kicked.",
              "modelConfidence": "high",
              "modelReason": "Tail.",
              "review": {
                "status": "known_mismatch",
                "note": "Figurative threat: this is not the animal-anatomy sense shown by SpanishDict."
              },
              "source": {
                "corpus": "OpenSubtitles en-es",
                "corpusLine": 6398070,
                "spanishDocument": "es/1972/68853/3655827.xml.gz",
                "spanishSegment": "738"
              }
            },
            {
              "id": "occ-ce25712fc857d81d",
              "spanish": "-Concepción, ven y brilla mi cola.",
              "english": "-Concepcion, come shine my tail.",
              "modelConfidence": "high",
              "modelReason": "Tail.",
              "review": {
                "status": "needs_review",
                "note": "Context is too thin to publish confidently."
              },
              "source": {
                "corpus": "OpenSubtitles en-es",
                "corpusLine": 38788269,
                "spanishDocument": "es/2011/1773578/6238598.xml.gz",
                "spanishSegment": "179"
              }
            },
            {
              "id": "occ-a14fd919b981cda7",
              "spanish": "¡Mi cola está ardiendo!",
              "english": "My tail, she's on fire!",
              "modelConfidence": "high",
              "modelReason": "Tail.",
              "review": {
                "status": "needs_review",
                "note": "Likely slang/body usage rather than a literal animal tail."
              },
              "source": {
                "corpus": "OpenSubtitles en-es",
                "corpusLine": 40024094,
                "spanishDocument": "es/2011/1980162/5811677.xml.gz",
                "spanishSegment": "302"
              }
            },
            {
              "id": "occ-7761a725c3acaad8",
              "spanish": "Digo lo que quiero y sólo oigo el sonido de tu cola.",
              "english": "I can say anything I want to, and there's no sound except the wag of your tail.",
              "modelConfidence": "high",
              "modelReason": "Tail of an animal.",
              "review": {
                "status": "unaudited"
              },
              "source": {
                "corpus": "OpenSubtitles en-es",
                "corpusLine": 2449886,
                "spanishDocument": "es/1952/44685/3402888.xml.gz",
                "spanishSegment": "327"
              }
            }
          ]
        },
        {
          "id": "b9b",
          "translation": "line",
          "context": "row of waiting people",
          "regions": [],
          "prominence": "common",
          "acceptedCount": 5,
          "shareOfSample": 0.2,
          "canonicalExample": {
            "spanish": "La cola para entrar al teatro es muy larga.",
            "english": "The line to get into the theater is very long."
          },
          "corpusCandidates": [
            {
              "id": "occ-62a4fa0cb3a6d9c1",
              "spanish": "¡Colas para el pan!",
              "english": "Bread lines are forming!",
              "modelConfidence": "high",
              "modelReason": "Line of waiting people.",
              "review": {
                "status": "unaudited"
              },
              "source": {
                "corpus": "OpenSubtitles en-es",
                "corpusLine": 8813320,
                "spanishDocument": "es/1983/86397/168222.xml.gz",
                "spanishSegment": "1163"
              }
            },
            {
              "id": "occ-03904e5e42b116be",
              "spanish": "Mira esto: ¡las colas, la espera, las pruebas...!",
              "english": "Look at this-- the lines, the waiting, the testing.",
              "modelConfidence": "high",
              "modelReason": "Lines of people waiting.",
              "review": {
                "status": "unaudited"
              },
              "source": {
                "corpus": "OpenSubtitles en-es",
                "corpusLine": 13925608,
                "spanishDocument": "es/1996/502741/3843512.xml.gz",
                "spanishSegment": "103"
              }
            },
            {
              "id": "occ-62ffa0131761d80b",
              "spanish": "HABIA COLA ALREDEDOR DE LA MANZANA",
              "english": "THERE WERE LINES AROUND THE BLOCK",
              "modelConfidence": "high",
              "modelReason": "Line of waiting people.",
              "review": {
                "status": "unaudited"
              },
              "source": {
                "corpus": "OpenSubtitles en-es",
                "corpusLine": 40948799,
                "spanishDocument": "es/2011/2397619/5084053.xml.gz",
                "spanishSegment": "2372"
              }
            },
            {
              "id": "occ-ca99f8b58f067e29",
              "spanish": "Pues ponte a la cola, dicen que hasta la reina suspira por él.",
              "english": "Then get in line, they say that even the queen pines for him.",
              "modelConfidence": "high",
              "modelReason": "Get in line.",
              "review": {
                "status": "unaudited"
              },
              "source": {
                "corpus": "OpenSubtitles en-es",
                "corpusLine": 47837289,
                "spanishDocument": "es/2013/2932142/5012754.xml.gz",
                "spanishSegment": "249"
              }
            }
          ]
        },
        {
          "id": "ff3",
          "translation": "queue",
          "context": "row of waiting people",
          "regions": [
            "United Kingdom"
          ],
          "prominence": "occasional",
          "acceptedCount": 1,
          "shareOfSample": 0.04,
          "canonicalExample": {
            "spanish": "El vendedor quiere que nos pongamos en cola.",
            "english": "The salesman wants us to form a queue."
          },
          "corpusCandidates": [
            {
              "id": "occ-2e4aefe1353f151e",
              "spanish": "Colas a la vuelta de la manzana.",
              "english": "Queues around the block.",
              "modelConfidence": "high",
              "modelReason": "Queue.",
              "review": {
                "status": "unaudited"
              },
              "source": {
                "corpus": "OpenSubtitles en-es",
                "corpusLine": 37716068,
                "spanishDocument": "es/2011/1565069/6220385.xml.gz",
                "spanishSegment": "461"
              }
            }
          ]
        }
      ],
      "otherSenses": [
        {
          "id": "095",
          "translation": "bum",
          "context": "buttocks",
          "regions": [
            "Latin America",
            "United Kingdom"
          ],
          "prominence": "uncommon_or_unseen",
          "acceptedCount": 0,
          "shareOfSample": 0.0,
          "canonicalExample": {
            "spanish": "Había agua en el banco donde me senté. Ahora tengo la cola mojada.",
            "english": "There was water on the bench where I sat down. Now my bum is wet."
          },
          "corpusCandidates": []
        },
        {
          "id": "10d",
          "translation": "bottom",
          "context": "buttocks",
          "regions": [
            "Latin America"
          ],
          "prominence": "uncommon_or_unseen",
          "acceptedCount": 0,
          "shareOfSample": 0.0,
          "canonicalExample": {
            "spanish": "¿Se me ve una cola enorme con este vaquero?",
            "english": "Does my bottom look huge in these jeans?"
          },
          "corpusCandidates": []
        },
        {
          "id": "2378",
          "translation": "tail",
          "context": "clothing",
          "regions": [],
          "prominence": "uncommon_or_unseen",
          "acceptedCount": 0,
          "shareOfSample": 0.0,
          "canonicalExample": {
            "spanish": "Hay chicle en la cola del frac.",
            "english": "There's gum on the tailcoat's tail."
          },
          "corpusCandidates": []
        },
        {
          "id": "2a6",
          "translation": "glue",
          "context": "substance",
          "regions": [],
          "prominence": "uncommon_or_unseen",
          "acceptedCount": 0,
          "shareOfSample": 0.0,
          "canonicalExample": {
            "spanish": "Pega eso con cola.",
            "english": "Stick that on with glue."
          },
          "corpusCandidates": []
        },
        {
          "id": "801",
          "translation": "caboose",
          "context": "train",
          "regions": [],
          "prominence": "uncommon_or_unseen",
          "acceptedCount": 0,
          "shareOfSample": 0.0,
          "canonicalExample": {
            "spanish": "El bandido está en la cola del tren.",
            "english": "The villain is in the train's caboose."
          },
          "corpusCandidates": []
        },
        {
          "id": "885",
          "translation": "train",
          "context": "clothing",
          "regions": [],
          "prominence": "uncommon_or_unseen",
          "acceptedCount": 0,
          "shareOfSample": 0.0,
          "canonicalExample": {
            "spanish": "La cola de mi vestido se arruinó en la lluvia.",
            "english": "The train of my dress got ruined in the rain."
          },
          "corpusCandidates": []
        },
        {
          "id": "88b",
          "translation": "soda",
          "context": "beverage",
          "regions": [
            "Dominican Republic",
            "Ecuador",
            "El Salvador"
          ],
          "prominence": "uncommon_or_unseen",
          "acceptedCount": 0,
          "shareOfSample": 0.0,
          "canonicalExample": {
            "spanish": "Dame una cola helada, por favor.",
            "english": "I'll have a cold soda, please."
          },
          "corpusCandidates": []
        },
        {
          "id": "939",
          "translation": "willy",
          "context": "penis",
          "regions": [
            "Spain",
            "United Kingdom"
          ],
          "prominence": "uncommon_or_unseen",
          "acceptedCount": 0,
          "shareOfSample": 0.0,
          "canonicalExample": {
            "spanish": "El bebé llora cuando hace pipí. Creo que le escuece la cola al pobrecito.",
            "english": "The baby cries when he's peeing. I think his willy stings, poor thing."
          },
          "corpusCandidates": []
        },
        {
          "id": "99e",
          "translation": "butt",
          "context": "buttocks",
          "regions": [
            "Latin America",
            "United States"
          ],
          "prominence": "uncommon_or_unseen",
          "acceptedCount": 0,
          "shareOfSample": 0.0,
          "canonicalExample": {
            "spanish": "La cola de la bebé está irritada.",
            "english": "The baby's butt is irritated."
          },
          "corpusCandidates": []
        },
        {
          "id": "a42",
          "translation": "weenie",
          "context": "penis",
          "regions": [
            "Spain",
            "United States"
          ],
          "prominence": "uncommon_or_unseen",
          "acceptedCount": 0,
          "shareOfSample": 0.0,
          "canonicalExample": {
            "spanish": "Mamá, a ese niño se le ve la cola.",
            "english": "Mom, I can see that boy's weenie."
          },
          "corpusCandidates": []
        }
      ]
    },
    {
      "id": "cura|cura|NOUN",
      "surface": "cura",
      "headword": "cura",
      "pos": "NOUN",
      "spanishDictUrl": "https://www.spanishdict.com/translate/cura",
      "sampled": 25,
      "accepted": 18,
      "coverage": 0.72,
      "abstained": 6,
      "belowGate": 1,
      "prominenceStatus": "usable_first_pass",
      "note": {
        "verdict": "clean_signal",
        "headline": "Two genuinely common senses",
        "detail": "The noun sample splits evenly between priest and cure; verb-shaped uses were allowed to abstain."
      },
      "importantSenses": [
        {
          "id": "875",
          "translation": "priest",
          "context": "religious",
          "regions": [],
          "prominence": "common",
          "acceptedCount": 9,
          "shareOfSample": 0.36,
          "canonicalExample": {
            "spanish": "El cura ofreció la misa el domingo por la mañana.",
            "english": "The priest offered Mass on Sunday morning."
          },
          "corpusCandidates": [
            {
              "id": "occ-75f52577b61a2f0e",
              "spanish": "¡Un pobre, señor cura!",
              "english": "A poor person, Father!",
              "modelConfidence": "high",
              "modelReason": "Refers to a religious priest.",
              "review": {
                "status": "unaudited"
              },
              "source": {
                "corpus": "OpenSubtitles en-es",
                "corpusLine": 3319290,
                "spanishDocument": "es/1957/50835/5885750.xml.gz",
                "spanishSegment": "355"
              }
            },
            {
              "id": "occ-71674ce50c51ea78",
              "spanish": "Señor cura...",
              "english": "Father...",
              "modelConfidence": "high",
              "modelReason": "Used as an address for a priest.",
              "review": {
                "status": "unaudited"
              },
              "source": {
                "corpus": "OpenSubtitles en-es",
                "corpusLine": 3639488,
                "spanishDocument": "es/1959/53033/4655277.xml.gz",
                "spanishSegment": "1047"
              }
            },
            {
              "id": "occ-bfb69ad9a02cdf8c",
              "spanish": "Lo que quieres, camarada cura... ..es ponernos a fregar los platos de los milicianos.",
              "english": "I've heard that before.",
              "modelConfidence": "high",
              "modelReason": "Refers to a religious priest.",
              "review": {
                "status": "unaudited"
              },
              "source": {
                "corpus": "OpenSubtitles en-es",
                "corpusLine": 13535926,
                "spanishDocument": "es/1996/113649/6942856.xml.gz",
                "spanishSegment": "512 511"
              }
            },
            {
              "id": "occ-f021fdfaec7887aa",
              "spanish": "Encuéntrate un joven cura bien guapo para que te guíe en todo esto.",
              "english": "Find one of those young priests with smoldering good looks who can sort of guide you through this.",
              "modelConfidence": "high",
              "modelReason": "Refers to a young priest.",
              "review": {
                "status": "unaudited"
              },
              "source": {
                "corpus": "OpenSubtitles en-es",
                "corpusLine": 15814262,
                "spanishDocument": "es/1999/164181/5703656.xml.gz",
                "spanishSegment": "670"
              }
            }
          ]
        },
        {
          "id": "b94",
          "translation": "cure",
          "context": "medical care",
          "regions": [],
          "prominence": "common",
          "acceptedCount": 9,
          "shareOfSample": 0.36,
          "canonicalExample": {
            "spanish": "Los médicos están buscando una cura para el ébola.",
            "english": "Doctors are trying to find a cure for Ebola."
          },
          "corpusCandidates": [
            {
              "id": "occ-9923d580c4680c52",
              "spanish": "A veces el sueño es la mejor cura.",
              "english": "Sometimes sleep is the best cure.",
              "modelConfidence": "high",
              "modelReason": "Refers to a medical cure.",
              "review": {
                "status": "unaudited"
              },
              "source": {
                "corpus": "OpenSubtitles en-es",
                "corpusLine": 6477531,
                "spanishDocument": "es/1973/122685/3334482.xml.gz",
                "spanishSegment": "278"
              }
            },
            {
              "id": "occ-c86c53a392c0ffe3",
              "spanish": "Audrey, hay muchas curas para un corazón roto pero nada como el salto de una trucha a la luz de la luna.",
              "english": "Audrey, there are many cures for a broken heart, but nothing quite like a trout's leap in the moonlight.",
              "modelConfidence": "high",
              "modelReason": "Refers to cures for a broken heart.",
              "review": {
                "status": "unaudited"
              },
              "source": {
                "corpus": "OpenSubtitles en-es",
                "corpusLine": 11518564,
                "spanishDocument": "es/1991/734839/5883147.xml.gz",
                "spanishSegment": "578"
              }
            },
            {
              "id": "occ-954c141816463218",
              "spanish": "- ¿Cree que hallaremos una cura?",
              "english": "Do you really think you can find a cure?",
              "modelConfidence": "high",
              "modelReason": "Refers to finding a medical cure.",
              "review": {
                "status": "unaudited"
              },
              "source": {
                "corpus": "OpenSubtitles en-es",
                "corpusLine": 14119363,
                "spanishDocument": "es/1996/708961/4049800.xml.gz",
                "spanishSegment": "75"
              }
            },
            {
              "id": "occ-8a67280e004c5775",
              "spanish": "Va a ayudarme a encontrar una cura para la enfermedad de Odo.",
              "english": "You're going to help me find a cure for Odo's disease.",
              "modelConfidence": "high",
              "modelReason": "Refers to a cure for a disease.",
              "review": {
                "status": "unaudited"
              },
              "source": {
                "corpus": "OpenSubtitles en-es",
                "corpusLine": 16314793,
                "spanishDocument": "es/1999/708535/4146742.xml.gz",
                "spanishSegment": "169"
              }
            }
          ]
        }
      ],
      "otherSenses": [
        {
          "id": "74f",
          "translation": "treatment",
          "context": "medical care",
          "regions": [],
          "prominence": "uncommon_or_unseen",
          "acceptedCount": 0,
          "shareOfSample": 0.0,
          "canonicalExample": {
            "spanish": "¿Estás seguro de que esta cura me ayudará?",
            "english": "Are you sure this treatment will help me?"
          },
          "corpusCandidates": []
        }
      ]
    },
    {
      "id": "sierra|sierra|NOUN",
      "surface": "sierra",
      "headword": "sierra",
      "pos": "NOUN",
      "spanishDictUrl": "https://www.spanishdict.com/translate/sierra",
      "sampled": 25,
      "accepted": 14,
      "coverage": 0.56,
      "abstained": 10,
      "belowGate": 1,
      "prominenceStatus": "insufficient_assignment_coverage",
      "note": {
        "verdict": "insufficient",
        "headline": "Not enough usable evidence",
        "detail": "Only 14 of 25 random occurrences passed the gate, so the prominence labels should not be published yet."
      },
      "importantSenses": [
        {
          "id": "995",
          "translation": "saw",
          "context": "tool",
          "regions": [],
          "prominence": "common",
          "acceptedCount": 10,
          "shareOfSample": 0.4,
          "canonicalExample": {
            "spanish": "El leñador utilizó una sierra para cortar el árbol.",
            "english": "The lumberjack used a saw to cut down the tree."
          },
          "corpusCandidates": [
            {
              "id": "occ-ddc33d99105c918b",
              "spanish": "Tiene un martillo, una sierra y un taladro.",
              "english": "It's got a hammer and a saw and a drill.",
              "modelConfidence": "high",
              "modelReason": "Refers to a tool used for cutting.",
              "review": {
                "status": "unaudited"
              },
              "source": {
                "corpus": "OpenSubtitles en-es",
                "corpusLine": 4472843,
                "spanishDocument": "es/1964/523045/6603585.xml.gz",
                "spanishSegment": "488"
              }
            },
            {
              "id": "occ-29160054f5fc1421",
              "spanish": "Me atravesaron el peto ocho veces, mi escudo está destrozado y mi espada mellada como una sierra. Que hablen ellos.",
              "english": "I am eight times thrust through the doublet, my buckler cut through, my sword hacked like a hand-saw.",
              "modelConfidence": "high",
              "modelReason": "Used in a simile comparing a sword to a saw.",
              "review": {
                "status": "unaudited"
              },
              "source": {
                "corpus": "OpenSubtitles en-es",
                "corpusLine": 4750519,
                "spanishDocument": "es/1965/59012/5285298.xml.gz",
                "spanishSegment": "338 339"
              }
            },
            {
              "id": "occ-f674272fafbcd7f6",
              "spanish": "Voy a necesitar una sierra.",
              "english": "I'm going to need a bone saw.",
              "modelConfidence": "high",
              "modelReason": "Refers to a surgical cutting tool.",
              "review": {
                "status": "unaudited"
              },
              "source": {
                "corpus": "OpenSubtitles en-es",
                "corpusLine": 14640996,
                "spanishDocument": "es/1997/574156/3935608.xml.gz",
                "spanishSegment": "133"
              }
            },
            {
              "id": "occ-436b5596cbad4986",
              "spanish": "¿Y esa sierra coincide con la que Brass encontró?",
              "english": "And this saw matches the one Brass found in Mrs. Bennett's garage?",
              "modelConfidence": "high",
              "modelReason": "Refers to a physical tool.",
              "review": {
                "status": "unaudited"
              },
              "source": {
                "corpus": "OpenSubtitles en-es",
                "corpusLine": 18075906,
                "spanishDocument": "es/2001/534753/5833539.xml.gz",
                "spanishSegment": "317"
              }
            }
          ]
        },
        {
          "id": "391",
          "translation": "mountain range",
          "context": "series of mountains",
          "regions": [],
          "prominence": "common",
          "acceptedCount": 4,
          "shareOfSample": 0.16,
          "canonicalExample": {
            "spanish": "Podía ver toda la sierra desde el avión.",
            "english": "I could see the whole mountain range from my plane."
          },
          "corpusCandidates": [
            {
              "id": "occ-03ec2c69db0d4fec",
              "spanish": "Le siguen sus huestes en la heroica huella... a través de montes, de valles, de sierras.",
              "english": "He is followed by his host on the heroic trail... through forests, through valleys, over hills.",
              "modelConfidence": "high",
              "modelReason": "Refers to a series of mountains.",
              "review": {
                "status": "unaudited"
              },
              "source": {
                "corpus": "OpenSubtitles en-es",
                "corpusLine": 7340952,
                "spanishDocument": "es/1977/333883/65528.xml.gz",
                "spanishSegment": "435"
              }
            },
            {
              "id": "occ-ef20f7c3e8f9e469",
              "spanish": "Es una sierra buena, mucha agua.",
              "english": "There's a lot of water in the hills.",
              "modelConfidence": "high",
              "modelReason": "Refers to a mountainous area.",
              "review": {
                "status": "unaudited"
              },
              "source": {
                "corpus": "OpenSubtitles en-es",
                "corpusLine": 12578668,
                "spanishDocument": "es/1994/110298/4162448.xml.gz",
                "spanishSegment": "1225"
              }
            },
            {
              "id": "occ-dc61f9e13b6ac853",
              "spanish": "Estamos sobre la Sierra Madre aproximándonos al PA.",
              "english": "We're over the sierra madres approaching the lz.",
              "modelConfidence": "high",
              "modelReason": "Part of a mountain range proper name.",
              "review": {
                "status": "unaudited"
              },
              "source": {
                "corpus": "OpenSubtitles en-es",
                "corpusLine": 30013698,
                "spanishDocument": "es/2008/1236303/4273140.xml.gz",
                "spanishSegment": "247"
              }
            },
            {
              "id": "occ-77859d4c7d169725",
              "spanish": "# Echaré de menos el sol en Sierra Nevada #",
              "english": "# I'll miss the sun on the Sierra Nevadas #",
              "modelConfidence": "high",
              "modelReason": "Part of a mountain range name.",
              "review": {
                "status": "unaudited"
              },
              "source": {
                "corpus": "OpenSubtitles en-es",
                "corpusLine": 34778797,
                "spanishDocument": "es/2010/1504319/4592030.xml.gz",
                "spanishSegment": "468"
              }
            }
          ]
        }
      ],
      "otherSenses": [
        {
          "id": "5f9",
          "translation": "mountains",
          "context": "series of mountains",
          "regions": [],
          "prominence": "uncommon_or_unseen",
          "acceptedCount": 0,
          "shareOfSample": 0.0,
          "canonicalExample": {
            "spanish": "Vivo cerca de la sierra para aprovechar el buen esquí de la región.",
            "english": "I live close to the mountains to take advantage of the good skiing in the region."
          },
          "corpusCandidates": []
        }
      ]
    }
  ]
};
