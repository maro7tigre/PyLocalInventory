class Animal():
    def __init__(self, name, voice, age):
        self.name = name
        self.voice = voice
        self.age = age
        self.speak()
    
    def speak(self):
        print(self.voice)
        
class dog(Animal):
    def __init__(self, name, voice, age):
        super().__init__(name, voice, age)
    

class city():
    def __init__(self):
        self.dog = dog(name="Rex", voice="Woof!", age=5)

my_city = city()
my_city.dog.speak()