import json
import os
from typing import List, Dict, Any, Optional
from collections import defaultdict
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import pandas as pd
from supabase import create_client, Client

# Load environment variables
load_dotenv()

# Initialize Supabase client
supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_KEY")

if not supabase_url or not supabase_key:
    raise ValueError("SUPABASE_URL and SUPABASE_KEY must be set in .env file")

# Initialize FastAPI
app = FastAPI(
    title="User Weaknesses Analysis API",
    description="API for analyzing user weaknesses in onboarding tests",
    version="1.0.0"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Update this in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Models
class SubtopicWeakness(BaseModel):
    subtopic: str
    section: str
    error_rate: float
    total_questions: int
    correct_answers: int
    incorrect_answers: int

class UserWeaknessResponse(BaseModel):
    user_id: str
    weaknesses: List[SubtopicWeakness]
    total_areas_analyzed: int

# Initialize Supabase client for dependency injection
def get_supabase_client() -> Client:
    return create_client(supabase_url, supabase_key)

@app.get("/")
def read_root():
    return {"message": "User Weaknesses Analysis API"}

@app.get("/api/user/{user_id}/weaknesses", response_model=UserWeaknessResponse)
def get_user_weaknesses(user_id: str, supabase: Client = Depends(get_supabase_client)):
    """
    Get the weak subjects for a specific user based on their onboarding test results.
    
    Args:
        user_id: The ID of the user to analyze
        
    Returns:
        A list of weak subjects with error rates and question counts
    """
    try:
        # Fetch user's test results from Supabase
        response = supabase.table("test_results") \
            .select("*") \
            .eq("user_id", user_id) \
            .in_("test_type", ["GMAT Onboarding Test", "GRE Onboarding Test"]) \
            .execute()
        
        test_results = response.data
        
        if not test_results:
            raise HTTPException(status_code=404, detail=f"No onboarding test data found for user {user_id}")
        
        # Process the test results to find weak areas
        user_comprehensive_stats = defaultdict(lambda: {'correct': 0, 'incorrect': 0, 'total': 0})
        
        for test in test_results:
            try:
                # Parse question details - handle both string and already parsed JSON
                questions = test['question_details']
                if isinstance(questions, str):
                    try:
                        questions = json.loads(questions)
                    except json.JSONDecodeError as e:
                        print(f"Error parsing question_details JSON: {e}")
                        continue
                
                # Now process the questions
                for question in questions:
                    # Get subtopic and section
                    subtopic = question.get('subtopic', 'Unknown')
                    section = question.get('section', 'Unknown')
                    
                    # Create a comprehensive key with only subtopic and section
                    comprehensive_key = f"{subtopic} | {section}"
                    
                    # Check if the question was answered correctly
                    is_correct = question.get('isCorrect', False)
                    
                    # Update counts
                    if is_correct:
                        user_comprehensive_stats[comprehensive_key]['correct'] += 1
                    else:
                        user_comprehensive_stats[comprehensive_key]['incorrect'] += 1
                    
                    user_comprehensive_stats[comprehensive_key]['total'] += 1
                    
            except (TypeError, KeyError) as e:
                print(f"Error processing test record: {str(e)}")
        
        # Calculate error rates
        for key, stats in user_comprehensive_stats.items():
            if stats['total'] > 0:
                stats['error_rate'] = (stats['incorrect'] / stats['total']) * 100
            else:
                stats['error_rate'] = 0
        
        # Convert to list of weaknesses and sort by error rate
        weaknesses = []
        for comprehensive_key, stats in user_comprehensive_stats.items():
            if stats['total'] >= 1:  # Include any question data
                subtopic, section = comprehensive_key.split(" | ")
                
                weaknesses.append(SubtopicWeakness(
                    subtopic=subtopic,
                    section=section,
                    error_rate=stats['error_rate'],
                    total_questions=stats['total'],
                    correct_answers=stats['correct'],
                    incorrect_answers=stats['incorrect']
                ))
        
        # Sort by error rate (highest first)
        weaknesses.sort(key=lambda x: x.error_rate, reverse=True)
        
        return UserWeaknessResponse(
            user_id=user_id,
            weaknesses=weaknesses,
            total_areas_analyzed=len(weaknesses)
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error analyzing user weaknesses: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("user_weaknesses_api:app", host="0.0.0.0", port=8000, reload=True)
