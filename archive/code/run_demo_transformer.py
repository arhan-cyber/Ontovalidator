import json
from svo_engine import (
    SVOVerificationEngine,
    MoERouter,
    SQLiteLexicalRetriever,
    SQLiteSemanticRetriever,
    SQLiteGraphRetriever,
    WeightedFusionEngine,
    SQLiteChunkStore,
    TransformerValidator,
)

raw_text = '''Title: The Global Impact of Climate-Resilient Agricultural Policies (2023-2028)

Introduction
------------
In the wake of the unprecedented heatwave of 2022 that devastated wheat yields across the Mid-Continental United States, the United Nations Food and Agriculture Organization (FAO) convened a special summit in Geneva to draft a series of climate-resilient agricultural policies. The summit’s flagship proposal, “Green Harvest 2025,” combined three core pillars: (1) the adoption of drought-tolerant crop varieties, (2) the subsidization of precision irrigation technologies, and (3) the establishment of regional carbon‑credit markets for farming practices.

Policy Pillar 1 – Drought‑Tolerant Crops
---------------------------------------
Researchers at the International Crop Research Institute (ICRI) released a genetically edited strain of *Triticum aestivum* (bread wheat) named “Aqua‑Wheat‑X1” in March 2023. Aqua‑Wheat‑X1 is engineered to express the *DREB1A* transcription factor, which up‑regulates osmoprotectant synthesis under water‑stress conditions. Field trials in Kansas showed a **28 % increase** in grain yield under a simulated 40 % reduction in precipitation, while maintaining protein content within industry standards.

Simultaneously, the Brazilian Agricultural Agency (ABA) introduced “Sorgo‑Sombra‑2024,” a sorghum cultivar capable of producing viable seed heads under canopy shade, enabling intercropping with leguminous trees. This intercropping system reduced soil erosion by **15 %**, increased nitrogen fixation, and cut pesticide usage by **22 %**.

Policy Pillar 2 – Precision Irrigation Subsidies
-----------------------------------------------
The EU Commission announced a €1.2 billion fund to subsidize **drip‑line sensors** for small‑holder farms in Southern Spain. Sensors transmit real‑time soil moisture data to a cloud‑based decision support system (DSS) built on a convolutional neural network trained on 10 years of meteorological data.

In early 2025, a pilot program in the Andalusian province of Granada reported that farms adopting the DSS reduced water consumption by **41 %** while increasing total horticultural output by **12 %**. However, a 2026 independent audit revealed that **7 %** of the deployed sensors suffered firmware bugs causing spurious over‑watering events during nocturnal temperature inversions.

Policy Pillar 3 – Regional Carbon‑Credit Markets
------------------------------------------------
In 2024, the Pacific Northwest established the “Carbon Farm Credit (CFC) Scheme,” awarding credits to farms that achieve a net sequestration rate of **≥ 0.8 t CO₂ ha⁻¹ yr⁻¹**. Credits are tradable on the Vancouver Carbon Exchange (VCX). By the end of 2027, the CFC scheme accounted for **3.4 %** of the VCX trading volume, with an average credit price of **$16 USD** per tonne.

Conversely, a 2028 investigative report by *EcoWatch* disclosed that several large agribusinesses were **double‑counting** credits by reporting both soil carbon accrual and biochar application under the same credit, inflating their carbon offset claims by an estimated **18 %**.

Cross‑Domain Interactions & Contradictions
-----------------------------------------
- The drought‑tolerant wheat (Aqua‑Wheat‑X1) requires **higher nitrogen fertilizer** to achieve optimal grain protein, potentially offsetting the carbon savings from reduced irrigation.
- The sorghum‑tree intercropping system improves nitrogen fixation, yet the associated increase in leaf litter has been linked to higher methane emissions during decomposition in tropical soils.
- Precision irrigation sensors rely on **continuous data transmission**, increasing electricity consumption; however, the DSS incorporates a low‑power sleep mode that cuts sensor draw by 30 % during periods of forecasted low evapotranspiration.
- The CFC scheme’s credit pricing model does not account for **non‑CO₂ greenhouse gases** (e.g., N₂O from fertilized fields), raising concerns about the net climate benefit of the overall policy suite.

Conclusion
----------
While “Green Harvest 2025” presents a coherent framework for enhancing agricultural resilience, the interplay of biophysical, technological, and market mechanisms yields a complex evidential landscape. Determining whether the policy suite *overall* reduces greenhouse‑gas emissions, improves food security, and maintains economic viability requires multi‑modal retrieval and nuanced reasoning across lexical, semantic, and graph stores.
''' 

query = "Considering the full set of Green Harvest 2025 policies, does the combined deployment of Aqua‑Wheat‑X1, precision irrigation sensors, and the Carbon Farm Credit scheme result in a net reduction of greenhouse‑gas emissions (including CO2, CH4, and N2O) while simultaneously increasing total grain yield across all participating regions?"

def run():
    engine = SVOVerificationEngine(
        router=MoERouter(),
        lexical_store=SQLiteLexicalRetriever('demo.sqlite'),
        semantic_store=SQLiteSemanticRetriever('demo.sqlite'),
        graph_store=SQLiteGraphRetriever('demo.sqlite'),
        fusion_engine=WeightedFusionEngine(),
        chunk_store=SQLiteChunkStore('demo.sqlite'),
        validator=TransformerValidator()
    )
    result = engine.verify(query, top_k=5)
    print(json.dumps(result, indent=2))

if __name__ == "__main__":
    run()
