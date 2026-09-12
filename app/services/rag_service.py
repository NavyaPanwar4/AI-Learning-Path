import numpy as np
from sklearn.metrics.pairwise import cosine_similarity
from app.utils.csv_handler import csv_handler
from app.services.embeddings_service import embeddings_service

class RAGService:
    def retrieve_context(self, missing_skills: list):
        resources_df = csv_handler.read_csv("resources.csv")
        projects_df = csv_handler.read_csv("projects.csv")
        
        if not missing_skills:
            return {"resources": [], "projects": []}
            
        skills_query = " ".join(missing_skills)
        query_emb = embeddings_service.get_embedding(skills_query)
        
        related_resources = []
        if not resources_df.empty:
            titles = resources_df['title'].astype(str).tolist()
            res_embs = embeddings_service.get_embeddings(titles)
            
            if res_embs:
                res_embs_array = np.array([e for e in res_embs if e is not None])
                if res_embs_array.size > 0:
                    sims = cosine_similarity([query_emb], res_embs_array)[0]
                    # Get top 5 resources
                    top_indices = sims.argsort()[-5:][::-1]
                    for idx in top_indices:
                        if sims[idx] > 0.2: # Threshold
                            row = resources_df.iloc[int(idx)]
                            related_resources.append({
                                "title": row['title'],
                                "url": row['url'],
                                "type": row['type']
                            })
                            
        related_projects = []
        if not projects_df.empty:
            descs = projects_df['description'].fillna("").astype(str).tolist()
            proj_embs = embeddings_service.get_embeddings(descs)
            
            if proj_embs:
                proj_embs_array = np.array([e for e in proj_embs if e is not None])
                if proj_embs_array.size > 0:
                    sims = cosine_similarity([query_emb], proj_embs_array)[0]
                    # Get top 3 projects
                    top_indices = sims.argsort()[-3:][::-1]
                    for idx in top_indices:
                        if sims[idx] > 0.2: # Threshold
                            row = projects_df.iloc[int(idx)]
                            related_projects.append({
                                "title": row['title'],
                                "description": row['description']
                            })
                            
        return {
            "resources": related_resources,
            "projects": related_projects
        }

rag_service = RAGService()
